"""Baked lighting of a replaced model, fitted to its new meshes (lighting phase 2).

The game lights many placed models from a baked "lighting" record of the block. A placed model finds its entries through keys that carry
the instance, the part, the mesh number and the mesh's vertex and index counts. A replacement changes those counts, so every lookup misses
and the model renders dark. TOD HD solved the same problem; its record parser, key tables and size pass are used here unchanged
(`vendor/hd/tod_hd_lighting.py`). What is new is the pairing of old and new meshes, because the importer builds its own sub-meshes:

  * the old meshes of the replaced part are told apart by their detail flag (near / far copy); the k-th new mesh of a kind takes over the
    key and entry of the k-th old mesh of that kind (more new meshes than old ones: not possible, nothing to attach the extra meshes to)
  * per-vertex colours: every new vertex takes the colour of the nearest old vertex of the same kind (all old meshes of the instance together)
  * single colours: kept when the mesh count is the same, else the mean of the old ones (the engine averages over the number of meshes)
  * only instances that provably belong to this model are touched (HD's ownership by unique id); a sibling model with the same counts is not
  * every key is re-sorted if needed and the record is laid out again by the engine's own size pass

An instance this cannot fit is left as it was and reported with a plain reason; the stage then falls back to unlit-by-baking for that
instance's placed copy (lighting phase 1). Nothing here writes outside the block it is given.
"""
import os
import struct
import sys

import numpy as np

from . import paths
from . import hdblock as _hdblock


class LightError(Exception):
    pass


def hl():
    p = os.path.join(paths.BACKEND, 'vendor', 'hd')
    if p not in sys.path:
        sys.path.append(p)
    import tod_hd_lighting
    return tod_hd_lighting


def _game():
    import tod_hd_game
    return tod_hd_game


# ------------------------------------------------------------------------------------------------ geometry
def model_geometry(HL, raw, ext, name):
    """The block's model record `name` -> {pivots: [[(vcount, icount)]], smb_flags, geometry}, or None."""
    low = name.lower()
    hits = [m for m in HL.model_mesh_geometry(raw, ext, low.split('/')[-1]) if m['name'].lower() == low]
    return hits[0] if len(hits) == 1 else None


def pairing(old_flags, new_flags):
    """[(new mesh, old mesh)]: the k-th near mesh takes the k-th old near mesh, and the same for far copies."""
    out = []
    for far in (0, 1):
        o = [j for j, f in enumerate(old_flags) if (f & 1) == far]
        n = [j for j, f in enumerate(new_flags) if (f & 1) == far]
        if len(n) > len(o):
            raise LightError('the new model has %d %s meshes and the original %d' % (len(n), 'far' if far else 'near', len(o)))
        out += list(zip(n, o))
    return out


def nearest(old_pos, new_pos):
    """For every new vertex the index of the nearest old vertex (squared distance, lowest index on ties)."""
    paths.ensure_cpu_guard()
    old_pos = np.asarray(old_pos, np.float64).reshape(-1, 3)
    new_pos = np.asarray(new_pos, np.float64).reshape(-1, 3)
    if not len(old_pos):
        raise LightError('the original mesh has no vertices')
    out = np.empty(len(new_pos), np.int64)
    step = max(1, 1500000 // len(old_pos))
    for s in range(0, len(new_pos), step):
        d = ((new_pos[s:s + step, None, :] - old_pos[None, :, :]) ** 2).sum(2)
        out[s:s + step] = d.argmin(1)
    return out


def mean_colour(cols):
    return sum(int(round(sum((c >> sh) & 255 for c in cols) / float(len(cols)))) << sh for sh in (0, 8, 16, 24))


# ------------------------------------------------------------------------------------------------ one model in one block
def retarget_model(data, ext, name, pivot, old_geo, new_geo):
    """`data`: the block with the NEW model already written. old_geo / new_geo: model_geometry() of the model before and after.
    -> (new bytes, report). Never raises for a plain "cannot fit"; report['status'] says what happened:
    'retargeted' (some or all instances), 'unchanged', 'none' (no baked lighting for it here), 'fallback' (nothing could be fitted)."""
    HL = hl()
    G = _game()
    rep = dict(model=name, status='none', pivot=pivot, instances=[], uids=[], fallback=[], records=[], patches=[], growth=0, regenerated=0)
    if old_geo is None or new_geo is None:
        rep.update(status='fallback', reason='the model record could not be read back')
        return data, rep
    if len(old_geo['pivots']) != len(new_geo['pivots']) or not 0 <= pivot < len(old_geo['pivots']):
        rep.update(status='fallback', reason='the part layout of the model changed')
        return data, rep
    for p, (a, b) in enumerate(zip(old_geo['pivots'], new_geo['pivots'])):
        if p != pivot and a != b:
            rep.update(status='fallback', reason='a part other than the replaced one changed')
            return data, rep
    old_m, new_m = old_geo['pivots'][pivot], new_geo['pivots'][pivot]
    old_f, new_f = old_geo['smb_flags'][pivot], new_geo['smb_flags'][pivot]
    if old_m == new_m:
        rep['status'] = 'unchanged'
        return data, rep
    try:
        pairs = pairing(old_f, new_f)
    except LightError as e:
        rep.update(status='fallback', reason=str(e))
        return data, rep
    sig = {j: tuple(c) for j, c in enumerate(old_m)}
    blk = _hdblock.Block(data, ext)
    recs = HL._parse_block(blk)
    if not recs:
        return data, rep
    pin = HL.pinned_instances(HL.instance_owners(data, ext), name)
    near_old = [j for j, f in enumerate(old_f) if not f & 1]
    far_old = [j for j, f in enumerate(old_f) if f & 1]
    same_shape = (len(new_m) == len(old_m) and [f & 1 for f in new_f] == [f & 1 for f in old_f])
    plans = []
    for rec in recs:
        pr = pin['records'].get(rec.index) or dict(own=[], shared={}, foreign={}, unresolved=[])
        own = set(pr['own'])
        matched, partial, superset = HL.match_instances(rec, sig, pivot, True)
        for i in partial:
            if i in own:
                rep['fallback'].append(dict(instance=i, reason='its baked lighting covers only some parts of the original'))
        for i in matched:
            if i in pr['shared']:
                rep['fallback'].append(dict(instance=i, reason='its lighting is shared with another model'))
            elif i in pr['unresolved']:
                rep['fallback'].append(dict(instance=i, reason='no placed copy of it is in this block'))
        by_inst = {}
        for k, w in enumerate(rec.keys):
            by_inst.setdefault(w[1] & 0xFFFF, []).append(k)
        keyp, regen, colour, entries = {}, {}, {}, []
        pay = blk.payloads[rec.index]
        uid_of = {v: rec.uid_keys[n] for n, v in enumerate(rec.uid_values)}
        for inst in matched:
            if inst not in own:
                continue
            ks = {}
            bad = None
            for j, cnt in sig.items():
                hit = [k for k in by_inst[inst] if (rec.keys[k][0] >> 16) & 0xFFFF == pivot and rec.keys[k][0] & 0xFFFF == j
                       and (rec.keys[k][2] & HL.COUNT_MASK, rec.keys[k][3] & HL.COUNT_MASK) == cnt]
                if len(hit) != 1:
                    bad = 'its keys for part %d mesh %d are not unique' % (pivot, j)
                    break
                ks[j] = hit[0]
            if bad is None:
                modes = {bool(rec.keys[k][1] & HL.SINGLE_BIT) for k in ks.values()}
                bufs = [rec.entries[rec.values[k]]['buffer'] is not None for k in ks.values()]
                if len(modes) != 1:
                    bad = 'it mixes single-colour and per-vertex keys'
                elif any(bufs) and not all(bufs):
                    bad = 'it mixes colour buffers and single colours'
                elif any(bufs) and modes == {True}:
                    bad = 'a single-colour key has a colour buffer'
                elif not any(bufs) and modes == {False}:
                    bad = 'a per-vertex key has no colour buffer'
            if bad:
                rep['fallback'].append(dict(instance=inst, reason=bad))
                continue
            vertex = all(rec.entries[rec.values[k]]['buffer'] is not None for k in ks.values())
            newk, newregen, newcol = {}, {}, {}
            try:
                if vertex:
                    src = {}
                    for far, group in ((0, near_old), (1, far_old)):
                        P, C = [], []
                        for j in group:
                            b = rec.entries[rec.values[ks[j]]]['buffer']
                            if b['count'] != old_m[j][0]:
                                raise LightError('a colour buffer holds %d colours, the mesh %d vertices' % (b['count'], old_m[j][0]))
                            P.append(np.asarray(old_geo['geometry'][pivot][j]['positions'], np.float64).reshape(-1, 3))
                            C.append(np.asarray(struct.unpack_from('<%dI' % b['count'], pay, b['data_offset']), np.uint32) if b['count'] else np.zeros(0, np.uint32))
                        src[far] = (np.concatenate(P) if P else np.zeros((0, 3)), np.concatenate(C) if C else np.zeros(0, np.uint32))
                for nj, oj in pairs:
                    k = ks[oj]
                    e = rec.entries[rec.values[k]]
                    w = rec.keys[k]
                    nv, ni = new_m[nj]
                    newk[k] = (nj, nv, ni)
                    if vertex:
                        P, C = src[new_f[nj] & 1]
                        geo = new_geo['geometry'][pivot][nj]
                        cols = C[nearest(P, geo['positions'])]
                        newregen[e['index']] = ([int(c) for c in cols], [int(x) for x in geo['indices']])
                        if any(x >= nv for x in newregen[e['index']][1]):
                            raise LightError('an index of the new mesh addresses a vertex that is not there')
                    elif not same_shape:
                        grp = far_old if old_f[oj] & 1 else near_old
                        newcol[e['index']] = mean_colour([rec.entries[rec.values[ks[j]]]['colour'] for j in grp])
            except LightError as ex:
                rep['fallback'].append(dict(instance=inst, reason=str(ex)))
                continue
            keyp.update(newk)
            regen.update(newregen)
            colour.update(newcol)
            entries += [rec.values[k] for k in newk]
            rep['instances'].append(inst)
            rep['uids'].append(list(uid_of[inst][-1]))
        if keyp:
            plans.append((rec, keyp, regen, colour))
    if not plans:
        rep['status'] = 'fallback' if rep['fallback'] else 'none'
        rep['reason'] = rep['fallback'][0]['reason'] if rep['fallback'] else ''
        return data, rep
    try:
        out = _apply(HL, G, data, ext, blk, plans, rep)
        rep['records'] = [p[0].name for p in plans]
        check_result(HL, G, data, out, ext, rep['records'], rep['patches'], {name.lower(): new_geo})
    except (LightError, G.GameDataError) as ex:
        rep.update(status='fallback', reason='the lighting could not be fitted (%s)' % ex, instances=[], uids=[], patches=[], records=[], growth=0, regenerated=0)
        return data, rep
    rep['status'] = 'retargeted'
    return out, rep


def _apply(HL, G, data, ext, blk, plans, rep):
    info = bytearray(blk.info)
    payloads = list(blk.payloads)
    shifts = []
    for rec, keyp, regen, colour in sorted(plans, key=lambda t: -t[0].R):
        if not regen:
            continue
        new_rec, new_pay = HL.relayout_record(rec, blk.payloads[rec.index], regen)
        growth = len(new_rec) - (rec.end - rec.R)
        info[rec.R:rec.end] = new_rec
        payloads[rec.index] = new_pay
        shifts.append((rec.R, rec.end, growth))
        rep['growth'] += growth
        rep['regenerated'] += len(regen)
    stage = blk
    if shifts:
        stage = _hdblock.Block(data, ext)
        stage.info = info
        stage.payloads = payloads
        stage = _hdblock.Block(stage.serialize(), ext)
    stage_recs = {r.index: r for r in HL._parse_block(stage)}
    info = bytearray(stage.info)
    for rec, keyp, regen, colour in plans:
        nr = stage_recs[rec.index]
        keys, values = list(nr.keys), list(nr.values)
        if keys != [tuple(w) for w in rec.keys] and not regen:
            raise LightError('the key table changed between two reads')
        for k, (nj, nv, ni) in keyp.items():
            w = keys[k]
            nw = ((w[0] & 0xFFFF0000) | nj, w[1], (w[2] & 0xFFF00000) | nv, (w[3] & 0xFFF00000) | ni)
            e = nr.entries[values[k]]
            c = e['key_copy']
            o = e['offset'] + 8
            if HL._masked(c) != HL._masked(w):
                raise LightError('entry %d: its key copy does not match its key' % e['index'])
            info[o:o + 16] = struct.pack('<4I', (c[0] & 0xFFFF0000) | nj, c[1], (c[2] & 0xFFF00000) | nv, (c[3] & 0xFFF00000) | ni)
            keys[k] = nw
            rep['patches'].append([rec.index, list(w), list(nw), e['index'], rep['model']])
        for ei, col in colour.items():
            struct.pack_into('<I', info, nr.entries[ei]['offset'] + 4, col)
        strict, found = HL._check_order(keys, values)
        if not (strict and found):
            keys, values = HL.resort_keys(keys, values)
            strict, found = HL._check_order(keys, values)
            if not (strict and found):
                raise LightError('the re-sorted key table fails the engine search')
            lo = nr.keys_off
            info[lo:lo + 16 * len(keys)] = b''.join(struct.pack('<4I', *w) for w in keys)
            if values:
                info[nr.values_off:nr.values_off + 2 * len(values)] = struct.pack('<%dH' % len(values), *values)
        else:
            for k in keyp:
                o = nr.keys_off + 16 * k
                info[o:o + 16] = struct.pack('<4I', *keys[k])
    stage.info = info
    return stage.serialize()


# ------------------------------------------------------------------------------------------------ proof
def check_result(HL, G, old_raw, new_raw, ext, records, patches, geos):
    """Independent read of the written block against the one it came from. Raises LightError.
    records: the lighting record names that may differ; patches: [record index, old key, new key, entry, model]; geos: {model name lower:
    model_geometry() of the written model}.
    Records: every record except those lighting records is byte-identical (INFO slice and payload);
    Counts: every retargeted key is found by the engine's own search, its entry holds the new mesh's vertex and index counts;
    Read-back: the strict parse of every lighting record passes all of HD's table checks, and the entries that were not patched are unchanged."""
    old, new = _hdblock.Block(old_raw, ext), _hdblock.Block(new_raw, ext)
    names = set(records)
    if [(r['type'], r['name']) for r in old.records] != [(r['type'], r['name']) for r in new.records]:
        raise LightError('the record list changed')
    shift = 0
    for ro, rn in zip(old.records, new.records):
        if ro['name'] in names and ro['type'] == HL.LIGHTING_TYPE:
            shift += (rn['end'] - rn['offset']) - (ro['end'] - ro['offset'])
            continue
        if old.info[ro['offset']:ro['end']] != new.info[rn['offset']:rn['end']] or old.payloads[ro['index']] != new.payloads[rn['index']]:
            raise LightError('record %s changed that was not meant to' % ro['name'])
    if len(new.info) != len(old.info) + shift:
        raise LightError('the block size does not add up')
    o_recs = {r.index: r for r in HL._parse_block(old)}
    n_recs = {r.index: r for r in HL._parse_block(new)}
    by_rec = {}
    for ri, w, nw, ei, model in patches:
        by_rec.setdefault(ri, []).append((tuple(w), tuple(nw), ei, model))
    for ri in sorted(n_recs):
        n = n_recs[ri]
        bad = [c for c, ok in n.checks.items() if not ok]
        if bad or n.problems:
            raise LightError('the lighting record does not read back (%s)' % ', '.join(bad or [str(n.problems[0])]))
    for ri, items in by_rec.items():
        o, n = o_recs[ri], n_recs[ri]
        if n.uid_keys != o.uid_keys or n.uid_values != o.uid_values or n.paths != o.paths or len(n.keys) != len(o.keys) or len(n.entries) != len(o.entries):
            raise LightError('the lighting record changed its instance tables')
        patched = {w: nw for w, nw, ei, model in items}
        want = {tuple(patched.get(tuple(w), tuple(w))): o.values[k] for k, w in enumerate(o.keys)}
        have = {tuple(w): v for w, v in zip(n.keys, n.values)}
        if len(want) != len(o.keys) or len(have) != len(n.keys) or have != want:
            raise LightError('the key table is not the expected mapping')
        touched = set()
        for w, nw, ei, model in items:
            touched.add(ei)
            pos = HL.engine_search(n.keys, nw)
            if pos is None or n.values[pos] != ei:
                raise LightError('the engine search does not find the new key of entry %d' % ei)
            e = n.entries[ei]
            nv, ni, single = nw[2] & HL.COUNT_MASK, nw[3] & HL.COUNT_MASK, bool(nw[1] & HL.SINGLE_BIT)
            if e['buffer'] is not None and (e['buffer']['count'] != nv or e['buffer']['index_count'] != ni):
                raise LightError('entry %d holds %d colours and %d indices, the key says %d and %d' % (
                    ei, e['buffer']['count'], e['buffer']['index_count'], nv, ni))
            if (e['buffer'] is None) != single:
                raise LightError('entry %d: the colour mode does not match its key' % ei)
            geo = geos.get(model.lower())
            if geo is not None:
                mesh = nw[0] & 0xFFFF
                cnt = geo['pivots'][(nw[0] >> 16) & 0xFFFF][mesh]
                if tuple(cnt) != (nv, ni):
                    raise LightError('mesh %d: the key says %d vertices and %d indices, the model has %d and %d' % (mesh, nv, ni, cnt[0], cnt[1]))
        for eo, en in zip(o.entries, n.entries):
            if eo['index'] in touched:
                continue
            if eo['key_copy'] != en['key_copy'] or eo['colour'] != en['colour'] or (eo['buffer'] is None) != (en['buffer'] is None):
                raise LightError('entry %d changed that was not meant to' % eo['index'])
            if eo['buffer'] is not None:
                bo, bn = eo['buffer'], en['buffer']
                ocol = old.payloads[ri][bo['data_offset']:bo['data_offset'] + bo['data_size']]
                ncol = new.payloads[ri][bn['data_offset']:bn['data_offset'] + bn['data_size']]
                ocp = bytes(old.info[bo['index_copy_offset']:bo['index_copy_offset'] + 2 * bo['index_copy_count']])
                ncp = bytes(new.info[bn['index_copy_offset']:bn['index_copy_offset'] + 2 * bn['index_copy_count']])
                if (bo['count'], bo['index_count'], ocol, ocp) != (bn['count'], bn['index_count'], ncol, ncp):
                    raise LightError('colour buffer of entry %d changed that was not meant to' % eo['index'])
    return dict(records=len(by_rec), keys=sum(len(v) for v in by_rec.values()), lighting_records=len(n_recs))


def verify(base_raw, new_raw, ext, lrep):
    """verify_block's lighting proof from the report apply_block made: reads both blocks again and checks records, counts and read-back
    (see check_result). Raises LightError. -> facts."""
    HL = hl()
    G = _game()
    done = [r for r in lrep if r['status'] == 'retargeted']
    recs = sorted({n for r in done for n in r['records']})
    patches = [p for r in done for p in r['patches']]
    geos = {r['model'].lower(): model_geometry(HL, new_raw, ext, r['model']) for r in done}
    got = check_result(HL, G, base_raw, new_raw, ext, recs, patches, geos)
    got.update(models=len(done), instances=sum(len(r['instances']) for r in done), entries_regenerated=sum(r['regenerated'] for r in done))
    return got
