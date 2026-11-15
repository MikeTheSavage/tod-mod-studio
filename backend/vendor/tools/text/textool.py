"""TOD text and localisation tool (GOG build): read every string, change and add strings, package them like the game
loads them.

  python textool.py list                                   TEXT assets per language block (entries, sizes)
  python textool.py export -o DIR [--langs uk,de,..]       every string with its id -> DIR/strings_<lang>.tsv/.json
  python textool.py roundtrip [--langs ..]                 codec + block rebuild proofs on every TEXT asset
  python textool.py edit EDIT.json --out DIR [--deploy GAMEDIR]
  python textool.py find TEXT [--lang uk]                  ids of the strings that contain TEXT
  python textool.py glyphs [--lang uk]                     characters the fonts cannot draw
  python textool.py refs -o refs.csv [--lang uk]           every fragment property that points at a string
  python textool.py names -o names.csv [--lang uk]         mission / weapon / move / power-up / vehicle / taxi names
  python textool.py subtitles -o subs.csv [--lang uk]      every Subtitle sound slot with its line times and ids
  python textool.py exe-strings                            the RT_STRING error dialogs inside TOD.exe

String id = <file>#<ordinal>, e.g. uk_HUD.txt#1. The ordinal is the 0-based entry number in the TEXT asset; that is
what the game stores everywhere (TextBox textslot_index, database properties, subtitle slots), never the key.
The same file names (uk_*.txt) exist in every language block (overdose_<lang>.main); ordinals line up across languages.

EDIT.json:
{ "description": "...",
  "langs": ["uk"],                                   language blocks to change (uk de fr es it); default ["uk"]
  "edits": [
    {"file": "uk_HUD.txt", "ordinal": 1, "value": "NEW TEXT"},           change a value (key kept)
    {"file": "uk_HUD.txt", "ordinal": 1, "key": "HUD_Gun_Heavy", "value": "..."},
    {"file": "uk_Menu.txt", "key": "MENU_Retry", "value": "..."},       by key (must be unique in the file)
    {"file": "uk_HUD.txt", "append": {"key": "HUD_MyNewLine", "value": "..."}}   new entry at the end
  ] }
Values are plain strings; "\\n" (backslash n) is the game's line break, %0..%9 are parameters, %% is a percent sign.

Every edit is verified before anything is written: the base blocks round-trip byte-identically; the rebuilt TEXT
asset decodes to exactly the intended entries; every other record of the block is byte-identical (shifted); header,
size table and payloads are unchanged; engine limits hold (no code unit with low byte 0, <= 1023 units, u16 stream
offsets); new ordinals above 1023 are refused (a TextBox stores textslot_index in 11 signed bits); characters the
fonts cannot draw are reported. Output: the rebuilt block(s), text_override.zip (STORED, read back through the
engine's OpenZip/FindFile port), configpc_line.txt, report.json.
"""
import argparse, csv, hashlib, json, os, re, shutil, struct, subprocess, sys, zipfile
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lowprio  # noqa: F401  (below-normal priority)
import todblock as tb
import texlib as tl
import fontlib

GOG_NAZ = os.environ.get('TOD_NAZ', r'C:\GOG Games\Total Overdose\blocks.naz')     # read only
LANGS = ['uk', 'de', 'fr', 'es', 'it']
ZIP_NAME = 'text_override.zip'
BASE_ARCHIVES = ['blocks.naz', 'sounds.naz', 'videos00.naz', 'videos01.naz']
FORBIDDEN_DEPLOY = [os.path.normcase(os.path.abspath(p)) for p in
                    (r'C:\GOG Games\Total Overdose',)]
TEXTBOX_INDEX_MAX = 1023


class Fail(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


_ARCH = None


def archive():
    global _ARCH
    if _ARCH is None:
        _ARCH = tb.Archive(GOG_NAZ)
    return _ARCH


def lang_blocks(lang):
    return ['data_pc/overdose_the_game/overdose/%s/overdose_%s.main' % (lang, lang),
            'data_pc/overdose_the_game/overdoseintro/%s/overdoseintro_%s.main' % (lang, lang)]


def load(entry):
    raw = archive().read(entry)
    b = tb.Block(raw, os.path.splitext(entry)[1])
    starts = tb.record_starts(bytes(b.info), b.n)
    return raw, b, starts


def text_assets(lang):
    """[(entry, block, starts, [(index, R, end, TextRecord)])]"""
    out = []
    for e in lang_blocks(lang):
        raw, b, starts = load(e)
        out.append((e, raw, b, starts, tl.find_text_records(bytes(b.info), starts)))
    return out


def short(name):
    return name.replace('\\', '/').split('/')[-1]


def esc(s):
    """TSV form: control characters, tab and '{' written as {U+XXXX}; everything else literal."""
    return ''.join('{U+%04X}' % ord(c) if ord(c) < 0x20 or c in '\t{' else c for c in s)


def unesc(s):
    return re.sub(r'\{U\+([0-9A-Fa-f]{4})\}', lambda m: chr(int(m.group(1), 16)), s)


# ------------------------------------------------------------------------------------------------ list / export
def cmd_list(a):
    for lang in a.langs:
        for e, raw, b, starts, recs in text_assets(lang):
            for i, R, end, t in recs:
                print('%-3s %-26s %-48s entries %5d  stream %6d B  tree %3d nodes  record %6d B' % (
                    lang, short(e), t.name, t.idx_n, t.st_n, t.nodes, end - R))


def cmd_export(a):
    os.makedirs(a.out, exist_ok=True)
    for lang in a.langs:
        rows = []
        js = dict(language=lang, source=GOG_NAZ, assets=[])
        for e, raw, b, starts, recs in text_assets(lang):
            for i, R, end, t in recs:
                ents = []
                for k, (key, val) in enumerate(t.pairs()):
                    ks, vs = tl.codes_to_str(key), tl.codes_to_str(val)
                    rows.append((short(t.name), k, ks, vs, short(e)))
                    ents.append(dict(ordinal=k, key=ks, value=vs))
                js['assets'].append(dict(block=e, asset=t.name, file=short(t.name), entries=ents))
        with open(os.path.join(a.out, 'strings_%s.tsv' % lang), 'w', encoding='utf-8', newline='') as f:
            f.write('id\tfile\tordinal\tkey\tvalue\tblock\n')
            for fn, k, ks, vs, bl in rows:
                f.write('%s#%d\t%s\t%d\t%s\t%s\t%s\n' % (fn, k, fn, k, esc(ks), esc(vs), bl))
        json.dump(js, open(os.path.join(a.out, 'strings_%s.json' % lang), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('%s: %d strings in %d assets -> %s' % (lang, len(rows), len(js['assets']),
                                                     os.path.join(a.out, 'strings_%s.tsv' % lang)))


# ------------------------------------------------------------------------------------------------ roundtrip
def rebuild_block(b, starts, replace):
    """replace: {record index: new bytes}. Returns new Block (records after an edited one shift; all records stay
    16-aligned because every record length is a multiple of 16)."""
    info = bytes(b.info)
    ends = starts[1:] + [len(info)]
    out = bytearray()
    for k, (R, E) in enumerate(zip(starts, ends)):
        out += replace.get(k, info[R:E])
    nb = tb.Block(b.serialize(), b.ext)
    nb.info = bytearray(out)
    return nb


def cmd_roundtrip(a):
    tot = dict(assets=0, identical=0, new_tree_decodes=0, blocks=0, blocks_identical=0, entries=0)
    fails = []
    for lang in a.langs:
        for e, raw, b, starts, recs in text_assets(lang):
            rep = {}
            for i, R, end, t in recs:
                pairs = t.pairs()
                tot['assets'] += 1
                tot['entries'] += len(pairs)
                new, note = tl.build_record(t, pairs, t.tree)
                if new == t.raw:
                    tot['identical'] += 1
                else:
                    fails.append('%s %s: identity re-encode differs' % (e, t.name))
                alt, _ = tl.build_record(t, pairs, tl.build_tree(tl.frequencies(pairs)))
                if tl.TextRecord(alt).pairs() == pairs:
                    tot['new_tree_decodes'] += 1
                else:
                    fails.append('%s %s: new-tree encode does not decode back' % (e, t.name))
                rep[i] = new
            nb = rebuild_block(b, starts, rep)
            tot['blocks'] += 1
            if nb.serialize() == raw:
                tot['blocks_identical'] += 1
            else:
                fails.append('%s: block rebuild differs' % e)
    print(json.dumps(dict(totals=tot, failures=fails), indent=1))
    return 1 if fails else 0


# ------------------------------------------------------------------------------------------------ fonts
_FONTS = {}


def fonts(lang='uk'):
    if lang not in _FONTS:
        raw, b, starts = load(lang_blocks(lang)[0])
        _FONTS[lang] = fontlib.read_fonts(bytes(b.info), starts)
    return _FONTS[lang]


def drawable(c, glyphs):
    """Glyph lookup 0x41AE90: exact code, else lower-case a-z / U+00E0..U+00FF retried as code - 0x20."""
    if c in glyphs:
        return True
    return (0x61 <= c <= 0x7A or (c & 0xFFE0) == 0xE0) and (c - 0x20) in glyphs


def undrawable(codes, glyphs):
    s = []
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0x5C and i + 1 < len(codes):          # \n line break, \x -> x
            i += 1
            if codes[i] != 0x6E and not drawable(codes[i], glyphs):
                s.append(codes[i])
        elif c == 0x25 and i + 1 < len(codes):        # %% -> %, %0..%9 parameter
            i += 1
            if codes[i] == 0x25 and not drawable(0x25, glyphs):
                s.append(0x25)
        elif c != 10 and not drawable(c, glyphs):
            s.append(c)
        i += 1
    return s


def cmd_glyphs(a):
    F = fonts(a.lang)
    main = F['/data/Fonts/ODPS2.font']['glyphs']
    bad = {}
    for e, raw, b, starts, recs in text_assets(a.lang):
        for i, R, end, t in recs:
            for k, (key, val) in enumerate(t.pairs()):
                for c in undrawable(val, main):
                    bad.setdefault(c, []).append('%s#%d' % (short(t.name), k))
    print('fonts in overdose_%s.main:' % a.lang)
    for nm, f in F.items():
        print('  %-42s %3d glyphs, cell %d px, %d keep-colour (icon) glyphs' % (
            nm, len(f['glyphs']), f['cell'], sum(1 for g in f['glyphs'].values() if g['keep_color'])))
    print('characters in %s text that ODPS2/ODPC cannot draw (drawn as nothing):' % a.lang)
    for c, ids in sorted(bad.items()):
        print('  U+%04X %-3s %4d uses, e.g. %s' % (c, repr(chr(c)), len(ids), ', '.join(ids[:4])))


# ------------------------------------------------------------------------------------------------ find
def cmd_find(a):
    needle = a.text.lower()
    for e, raw, b, starts, recs in text_assets(a.lang):
        for i, R, end, t in recs:
            for k, (key, val) in enumerate(t.pairs()):
                ks, vs = tl.codes_to_str(key), tl.codes_to_str(val)
                if needle in ks.lower() or needle in vs.lower():
                    print('%s#%d\t%s\t%s' % (short(t.name), k, ks, esc(vs)))


# ------------------------------------------------------------------------------------------------ edit
def resolve_edits(spec_edits, lang, t_by_file, plan=None):
    """-> {file: (TextRecord, new pairs, [changes])}"""
    plan = {} if plan is None else plan
    for ed in spec_edits:
        fn = ed['file']
        fn = fn if fn.endswith('.txt') else fn + '.txt'
        if fn not in t_by_file:
            raise Fail('%s: no TEXT asset %s in the %s blocks' % (lang, fn, lang))
        t = t_by_file[fn][3]
        if fn not in plan:
            plan[fn] = (t, [list(map(list, p)) for p in t.pairs()], [])
        _, pairs, changes = plan[fn]
        if 'append' in ed:
            key = tl.str_to_codes(ed['append'].get('key', ''))
            val = tl.str_to_codes(ed['append'].get('value', ''))
            pairs.append([key, val])
            changes.append(dict(op='append', ordinal=len(pairs) - 1, key=tl.codes_to_str(key)))
            continue
        if isinstance(ed.get('ordinal'), list):
            for o in ed['ordinal']:
                sub = dict(ed); sub['ordinal'] = o
                resolve_edits([sub], lang, t_by_file, plan)
            continue
        if 'ordinal' in ed:
            k = int(ed['ordinal'])
        elif 'key' in ed:
            hits = [i for i, p in enumerate(pairs) if tl.codes_to_str(p[0]) == ed['key']]
            if len(hits) != 1:
                raise Fail('%s: key %r matches %d entries; give "ordinal"' % (fn, ed['key'], len(hits)))
            k = hits[0]
        else:
            raise Fail('edit needs "ordinal", "key" or "append": %s' % ed)
        if not 0 <= k < len(pairs):
            raise Fail('%s: ordinal %d out of range (0..%d)' % (fn, k, len(pairs) - 1))
        if 'key' in ed and 'ordinal' in ed:
            pairs[k][0] = tl.str_to_codes(ed['key'])
        if 'value' in ed:
            pairs[k][1] = tl.str_to_codes(ed['value'])
        if 'prefix' in ed:
            pairs[k][1] = tl.str_to_codes(ed['prefix']) + pairs[k][1]
        if 'suffix' in ed:
            pairs[k][1] = pairs[k][1] + tl.str_to_codes(ed['suffix'])
        changes.append(dict(op='set', ordinal=k, key=tl.codes_to_str(pairs[k][0])))
    return plan


def write_zip(path, entries):
    tmp = path + '.part'
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        for entry, data in entries:
            zi = zipfile.ZipInfo(entry, date_time=(2005, 8, 21, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 0
            zi.external_attr = 0
            zf.writestr(zi, data)
    os.replace(tmp, path)
    st = os.stat(GOG_NAZ)
    os.utime(path, (st.st_atime, st.st_mtime))
    z = tb.Archive(path)
    out = []
    for entry, data in entries:
        hit = z.find('/' + entry)
        if z.naz or hit is None or hit[2] != entry or hit[1] != len(data):
            raise Fail('zip: engine lookup failed for %s' % entry)
        with open(path, 'rb') as f:
            f.seek(hit[0])
            if f.read(hit[1]) != data:
                raise Fail('zip: bytes at the engine offset differ for %s' % entry)
        out.append(dict(entry=entry, data_offset=hit[0], bytes=len(data), sha256=sha(data), engine_lookup_ok=True))
    collide = [n for c, (_, _, n) in archive().table.items() if c in z.table and n != z.table[c][2]]
    if collide:
        raise Fail('zip: name hash collides with ' + collide[0])
    return dict(zip=path, zip_bytes=os.path.getsize(path), entries=out)


def game_running():
    out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True).stdout.lower()
    return '"tod.exe"' in out or '"totaloverdose.exe"' in out


def verify(raw, b, starts, nb_bytes, edited, intended):
    """Independent re-parse of the rebuilt block."""
    chk = {}
    nb = tb.Block(nb_bytes, b.ext)
    ninfo = bytes(nb.info)
    nstarts = tb.record_starts(ninfo, nb.n)
    chk['records'] = '%d (was %d)' % (len(nstarts), len(starts))
    if len(nstarts) != len(starts):
        raise Fail('record count changed')
    oinfo = bytes(b.info)
    oends = starts[1:] + [len(oinfo)]
    nends = nstarts[1:] + [len(ninfo)]
    same = 0
    for k in range(len(starts)):
        o = oinfo[starts[k]:oends[k]]
        n = ninfo[nstarts[k]:nends[k]]
        if k in edited:
            t = tl.TextRecord(n)
            got = [list(map(list, p)) for p in t.pairs()]
            if got != intended[k]:
                raise Fail('record %d does not decode to the intended entries' % k)
            if n[:0x20] != o[:0x20] or n[0x50:t.root] != o[0x50:t.root]:
                raise Fail('record %d header / name area changed (only the three list fields may change)' % k)
        elif o != n:
            raise Fail('record %d (%s) changed' % (k, tb.record_name(oinfo, starts[k])))
        else:
            same += 1
    chk['other_records_identical'] = same
    if (nb.timestamp, nb.prop_ck, nb.cmd_ck, nb.prefix) != (b.timestamp, b.prop_ck, b.cmd_ck, b.prefix):
        raise Fail('block header changed')
    if nb.payloads != b.payloads:
        raise Fail('payloads changed')
    chk['header_sizes_payloads'] = 'unchanged (info size %d -> %d)' % (len(oinfo), len(ninfo))
    return chk


def cmd_edit(a):
    spec = json.load(open(a.edit, encoding='utf-8'))
    langs = spec.get('langs', ['uk'])
    os.makedirs(a.out, exist_ok=True)
    rep = dict(edit=spec, blocks=[], warnings=[])
    zip_entries = []
    try:
        for lang in langs:
            if lang not in LANGS:
                raise Fail('unknown language %r' % lang)
            assets = text_assets(lang)
            t_by_file = {}
            for e, raw, b, starts, recs in assets:
                for item in recs:
                    t_by_file[short(item[3].name)] = (e, raw, b, item[3], item[0], starts)
            plan = resolve_edits(spec['edits'], lang, {k: (v[0], v[1], v[2], v[3]) for k, v in t_by_file.items()})
            glyphs = fonts(lang)['/data/Fonts/ODPS2.font']['glyphs']
            by_block = {}
            for fn, (t, pairs, changes) in plan.items():
                e, raw, b, _, k, starts = t_by_file[fn]
                for ch in changes:
                    key, val = pairs[ch['ordinal']]
                    err, warn = tl.check_entry(key, val)
                    if err:
                        raise Fail('%s %s#%d: %s' % (lang, fn, ch['ordinal'], '; '.join(err)))
                    if ch['op'] == 'append' and ch['ordinal'] > TEXTBOX_INDEX_MAX:
                        raise Fail('%s %s: new ordinal %d > %d (TextBox textslot_index is 11-bit signed)' % (
                            lang, fn, ch['ordinal'], TEXTBOX_INDEX_MAX))
                    miss = undrawable(val, glyphs)
                    if miss:
                        warn.append('the fonts cannot draw %s' % ' '.join('U+%04X' % c for c in sorted(set(miss))))
                    for w in warn:
                        rep['warnings'].append('%s %s#%d: %s' % (lang, fn, ch['ordinal'], w))
                new, note = tl.build_record(t, [tuple(p) for p in pairs])
                by_block.setdefault(e, dict(raw=raw, b=b, starts=starts, replace={}, intended={}, notes=[]))
                by_block[e]['replace'][k] = new
                by_block[e]['intended'][k] = pairs
                by_block[e]['notes'].append(dict(file=fn, record=k, changes=changes, **note,
                                                 old_record_bytes=len(t.raw)))
            for e, d in by_block.items():
                raw, b, starts = d['raw'], d['b'], d['starts']
                if rebuild_block(b, starts, {}).serialize() != raw:
                    raise Fail('%s: base block does not round-trip' % e)
                for i, R, end, t in tl.find_text_records(bytes(b.info), starts):
                    if tl.build_record(t, t.pairs(), t.tree)[0] != t.raw:
                        raise Fail('%s: %s does not re-encode identically' % (e, t.name))
                nb = rebuild_block(b, starts, d['replace'])
                out = nb.serialize()
                chk = verify(raw, b, starts, out, set(d['replace']), d['intended'])
                fn = os.path.join(a.out, lang + '_' + os.path.basename(e))
                open(fn, 'wb').write(out)
                rep['blocks'].append(dict(lang=lang, entry=e, base_sha256=sha(raw), out=fn, out_sha256=sha(out),
                                          out_bytes=len(out), assets=d['notes'], checks=chk))
                zip_entries.append((e, out))
        for fb in spec.get('fragment_ops', []):
            # references to new strings: fragment edits through the verified fragment writer (tools/fragment_writer)
            import fragtool as ft
            T = ft.types()
            raw, entry, ext = ft.load_block_bytes(fb['block'])
            if entry in [x[0] for x in zip_entries]:
                raise Fail('%s is edited twice' % entry)
            r0 = ft.roundtrip_block(raw, ext, T)
            if r0['fail'] or not r0['block_identical']:
                raise Fail('fragment base block does not round-trip: %s' % entry)
            old, nb, docs, intended = ft.apply_ops(raw, ext, fb['ops'], T)
            out = nb.serialize()
            vr, _ = ft.verify_block(old, out, ext, docs, intended, T)
            fn = os.path.join(a.out, os.path.basename(entry))
            open(fn, 'wb').write(out)
            rep['blocks'].append(dict(lang='shared', entry=entry, base_sha256=sha(raw), out=fn, out_sha256=sha(out),
                                      out_bytes=len(out), assets=[], checks=dict(fragment_writer=vr)))
            zip_entries.append((entry, out))
        zp = os.path.join(a.out, ZIP_NAME)
        rep['zip'] = write_zip(zp, zip_entries)
        line = 'filesystem = ' + ', '.join([ZIP_NAME] + BASE_ARCHIVES)
        open(os.path.join(a.out, 'configpc_line.txt'), 'w').write(line + '\n')
        rep['configpc_line'] = line
        if a.deploy:
            gd = os.path.normcase(os.path.abspath(a.deploy))
            if any(gd == f or gd.startswith(f + os.sep) for f in FORBIDDEN_DEPLOY):
                raise Fail('refusing to deploy into %s' % a.deploy)
            if game_running():
                raise Fail('a game is running; not touching any game folder now')
            shutil.copy2(zp, os.path.join(a.deploy, ZIP_NAME))
            rep['deploy'] = dict(to=a.deploy, note='put %s first on the filesystem line of configpc.txt' % ZIP_NAME)
        rep['result'] = 'PASS'
    except Exception as ex:      # Fail, ValueError, KeyError, fragment writer errors: nothing packaged
        rep['result'] = 'FAIL: %s' % ex
    json.dump(rep, open(os.path.join(a.out, 'report.json'), 'w', encoding='utf-8'), indent=1, default=str,
              ensure_ascii=False)
    print(json.dumps(dict(result=rep['result'], zip=rep.get('zip', {}).get('zip'), configpc_line=rep.get('configpc_line'),
                          blocks=[dict(entry=x['entry'], assets=[dict(file=n['file'], tree=n['tree'],
                                                                      changes=len(n['changes']))
                                                                 for n in x['assets']], checks=x['checks'])
                                  for x in rep['blocks']], warnings=rep['warnings']), indent=1, ensure_ascii=True))
    return 0 if rep['result'] == 'PASS' else 1


# ------------------------------------------------------------------------------------------------ fragments
# Which text file a fragment property points into. Established by the keys found at the stored ordinals
# (e.g. MissionDict Mission_Name 64 -> uk_Mission.txt#64 MIS_MM010_name); see docs/subsystem_text.md section 6.
REF_MAP = {
    'Subtitle(SoundSlot)|StartSlotValue': 'uk_Dialog.txt', 'Subtitle(SoundSlot)|EndSlotValue': 'uk_Dialog.txt',
    '*|DisplayText': 'uk_Objective.txt', '*|CounterText': 'uk_Objective.txt', '*|FeedbackText': 'uk_Objective.txt',
    '*|EffectText': 'uk_Misc.txt', '*|HUDName': 'uk_Misc.txt',
    '*|EntryText': 'uk_Menu.txt', '*|ValueString1': 'uk_Menu.txt', '*|ValueString2': 'uk_Menu.txt',
    '*|ValueString3': 'uk_Menu.txt', '*|ValueString4': 'uk_Menu.txt', '*|ValueString5': 'uk_Menu.txt',
    '*|MenuCaption': 'uk_Menu.txt', '*|MenuDescription': 'uk_Menu.txt', '*|ZAP_name': 'uk_Menu.txt',
    '*|Misc_Game_title': 'uk_Misc.txt',
    'database_string_dict(NodeLogical)|*': 'uk_Menu.txt',
    'HUD_power_up(NodeLogical)|*': 'uk_HUD.txt',
    '*|ComboStringValue': 'uk_HUD.txt', '*|PopupText': 'uk_HUD.txt', '*|MoveName': 'uk_HUD.txt',
    '*|AwardStringValue': 'uk_HUD.txt', '*|AwardString': 'uk_HUD.txt',
    '*|Mission_Name': 'uk_Mission.txt', '*|Mission_Real_Name': 'uk_Mission.txt',
    '*|Mission_Description': 'uk_Mission.txt', '*|Mission_teaser': 'uk_Mission.txt',
    '*|BonusMission_name': 'uk_Mission.txt', '*|LoadScreen_Main_Text': 'uk_Mission.txt',
    '*|LoadScreen_Mid_Text': 'uk_Mission.txt', '*|LoadScreen_Low_Text': 'uk_Mission.txt',
    '*|Award_Name': 'uk_Mission.txt',
    'tutorial_root(NodeLogical)|CaptionIndex': 'uk_Tutorial_Menu.txt',
    'tutorial_root(NodeLogical)|DescriptionIndex': 'uk_Tutorial_Menu.txt',
    'tutorial_menu_root(NodeLogical)|CaptionIndex': 'uk_Tutorial_Menu.txt',
    '*|TutorialText': 'uk_Tutorial.txt / uk_Tutorial_PC.txt', '*|Alt_TutorialText': 'uk_Tutorial.txt / uk_Tutorial_PC.txt',
    'IntroStringDB(NodeLogical)|*': 'IntroScene.txt',
    'TextBox|textslot_index': '(TextSlot chosen by script)',
}
NOT_TEXT = {'OneshotGoodieIndex', 'stopmessage', 'Award_1_Type', 'Award_2_Type', 'Award_3_Type', 'Number_of_Awards_1',
            'Number_of_Awards_2', 'Number_of_Awards_3', 'Award_Achived', 'Award_Type', 'GoodieAward', 'FirstAward',
            'SecondAward', 'ThirdAward', 'FourthAward', 'FifthAward', 'MenuIndex', 'TutorialIndex',
            'TutorialEntryNum', 'current_index', 'Award', 'TestIndex', 'TextSymbol'}
TEXTISH = re.compile(r'text|caption|descr|teaser|title|name|msg|message|slotvalue|award|string|label|popup|'
                     r'feedback|tutorial|menu_|_text|index', re.I)
EXCL = re.compile(r'sound|anim|texture|music|emitter|track|point|bone|pivot|model|weaponindex|nextgun|pinata', re.I)


def ref_file(typ, prop):
    for k in ('%s|%s' % (typ, prop), '*|%s' % prop, '%s|*' % typ):
        if k in REF_MAP:
            return REF_MAP[k]
    if typ.endswith('(TextBox)') and prop == 'textslot_index':
        return REF_MAP['TextBox|textslot_index']
    return None


def iter_fragment_entities(blocks=None):
    import todfrag as tf
    import fragedit as fe
    T = tf.Types()
    names = blocks or sorted(v[2] for v in archive().table.values())
    for e in names:
        if os.path.splitext(e)[1].lower() not in tb.BLOCK_EXTS:
            continue
        b = tb.load_block(archive(), e)
        info = bytes(b.info)
        for k, R in enumerate(tb.record_starts(info, b.n)):
            if tb.u32(info, R) != 4:
                continue
            nm = tb.record_name(info, R)
            d = fe.FragDoc(b.payloads[k], T, nm)
            for n in d.created_ids():
                props = {}
                for r in d.sets_of(n):
                    props[T.name(r.prop)] = (r.prop, T.ptype(r.prop), d.frag.value(r))
                yield e, nm, n, d.type_of(n) or '', d.path_of(n), props


def text_table(lang):
    tab = {}
    for e, raw, b, starts, recs in text_assets(lang):
        for i, R, end, t in recs:
            tab[short(t.name)] = [(tl.codes_to_str(k), tl.codes_to_str(v)) for k, v in t.pairs()]
    return tab


def lookup(tab, fname, idx, lang):
    if not fname or fname.startswith('('):
        return '', ''
    f = fname.split(' / ')[0]
    rows = tab.get(f)
    if rows is None or not isinstance(idx, int) or not 0 <= idx < len(rows):
        return '', ''
    return rows[idx]


def cmd_refs(a):
    tab = text_table(a.lang)
    n = 0
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['block', 'fragment', 'node', 'path', 'type', 'property', 'ordinal', 'file', 'key', 'value'])
        for e, nm, node, typ, path, props in iter_fragment_entities():
            for pname, (pi, pty, v) in props.items():
                if pty not in ('integer', 'list(integer)') or pname in NOT_TEXT:
                    continue
                fname = ref_file(typ, pname)
                if fname is None and not (TEXTISH.search(pname) and not EXCL.search(pname)):
                    continue
                vals = v if isinstance(v, list) else [v]
                for x in vals:
                    key, val = lookup(tab, fname, x, a.lang)
                    w.writerow([e, short(nm), '0x%08X' % node, path, typ, pname, x, fname or '(unresolved)',
                                key, esc(val)])
                    n += 1
    print('%d references -> %s' % (n, a.out))


NAME_SETS = [  # (label, fragment substring, entity type, properties)
    ('mission', 'MissionDict.fragment', 'database_mission_award(NodeLogical)',
     ['Mission_Name', 'Mission_Real_Name', 'Mission_Description', 'Mission_teaser', 'BonusMission_name',
      'LoadScreen_Main_Text', 'LoadScreen_Mid_Text', 'LoadScreen_Low_Text']),
    ('weapon', 'WeaponDict.fragment', 'database_weapon_subtype(NodeLogical)', ['PopupText', 'ComboStringValue']),
    ('stunt (unique combo move)', 'UniqueComboMovesDict.fragment', 'database_unique_combo_move(Folder)', ['MoveName']),
    ('combo move', '', 'database_combo_type(NodeLogical)', ['ComboStringValue']),
    ('combo string', '', 'database_combo_string_ID(NodeLogical)', ['ComboStringValue']),
    ('enemy state', '', 'database_combo_enemy_state(NodeLogical)', ['ComboStringValue']),
    ('vehicle', '', 'database_vehicle_type(Node)', ['ComboStringValue']),
    ('animation move', '', 'database_animslot(MotionAnimSlot)', ['ComboStringValue']),
    ('award', '', 'database_mission_award_info(NodeLogical)', ['Award_Name']),
    ('taxi point', '', 'database_taxipoint(Node)', ['MenuDescription']),
    ('zap (taxi) location', '', 'database_zap_type(Node)', ['ZAP_name']),
    ('power-up (loco move)', '', 'HUD_power_up(NodeLogical)', 'Menu_Power_up_'),
    ('menu string', '', 'database_string_dict(NodeLogical)', 'Menu_'),
    ('tutorial', '', 'tutorial_root(NodeLogical)', ['CaptionIndex', 'DescriptionIndex']),
]


def cmd_names(a):
    tab = text_table(a.lang)
    shared = [e for e in sorted(v[2] for v in archive().table.values()) if e.endswith('/shared/overdose.main')]
    rows = []
    for e, nm, node, typ, path, props in iter_fragment_entities(shared):
        for label, fr, ty, plist in NAME_SETS:
            if typ != ty or (fr and not nm.endswith(fr)):
                continue
            for pname, (pi, pty, v) in props.items():
                if pty != 'integer':
                    continue
                if isinstance(plist, str) and not pname.startswith(plist):
                    continue
                if isinstance(plist, list) and pname not in plist:
                    continue
                fname = ref_file(typ, pname)
                key, val = lookup(tab, fname, v, a.lang)
                rows.append([label, path, pname, v, fname, key, esc(val), short(nm)])
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['kind', 'entity', 'property', 'ordinal', 'file', 'key', 'value', 'fragment'])
        w.writerows(rows)
    print('%d names -> %s' % (len(rows), a.out))


def cmd_subtitles(a):
    tab = text_table(a.lang)
    dia = tab['uk_Dialog.txt']
    n = 0
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['block', 'fragment', 'slot', 'stream', 'line', 'on_s', 'off_s', 'ordinal', 'key', 'value'])
        for e, nm, node, typ, path, props in iter_fragment_entities():
            if not typ.startswith('Subtitle('):
                continue
            tlist = props.get('Timelist', (0, 0, []))[2] or []
            start = props.get('StartSlotValue', (0, 0, 0))[2] or 0
            stream = props.get('streaming_sound', (0, 0, ''))[2] or props.get('sound', (0, 0, ''))[2] or ''
            t = 0.0
            for k in range(max(0, len(tlist) - 1)):          # rule of 0x7AB460 (cutscene doc 3.3)
                t += tlist[k]
                on, off = t, t + tlist[k + 1]
                o = start + k
                key, val = dia[o] if 0 <= o < len(dia) else ('', '')
                w.writerow([e, short(nm), path, stream, k, round(on, 3), round(off, 3), o, key, esc(val)])
                n += 1
    print('%d subtitle lines -> %s' % (n, a.out))


def cmd_exe_strings(a):
    import peres
    r = peres.load()
    names = ['uk', 'fr', 'it', 'de', 'es', 'dk']
    for (i, lid), s in sorted(r.items()):
        base = i - i % 10
        print('%3d (%s, language %s)\t%s' % (i, {220: 'title', 230: 'msg 0', 240: 'msg 1', 250: 'msg 2', 260: 'msg 4',
                                                 270: 'msg 5', 280: 'msg 3', 290: 'msg 6'}.get(base, '?'),
                                             names[i % 10] if i % 10 < 6 else '?', esc(s)))


def main():
    global GOG_NAZ
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--naz', default=None, help='blocks.naz to read (default: the GOG install, read only)')
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('list'); p.add_argument('--langs', default='uk')
    p = sp.add_parser('export'); p.add_argument('-o', '--out', required=True); p.add_argument('--langs', default=','.join(LANGS))
    p = sp.add_parser('roundtrip'); p.add_argument('--langs', default=','.join(LANGS))
    p = sp.add_parser('edit'); p.add_argument('edit'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    p = sp.add_parser('find'); p.add_argument('text'); p.add_argument('--lang', default='uk')
    p = sp.add_parser('glyphs'); p.add_argument('--lang', default='uk')
    p = sp.add_parser('refs'); p.add_argument('-o', '--out', required=True); p.add_argument('--lang', default='uk')
    p = sp.add_parser('names'); p.add_argument('-o', '--out', required=True); p.add_argument('--lang', default='uk')
    p = sp.add_parser('subtitles'); p.add_argument('-o', '--out', required=True); p.add_argument('--lang', default='uk')
    sp.add_parser('exe-strings')
    a = ap.parse_args()
    if a.naz:
        GOG_NAZ = a.naz
    if hasattr(a, 'langs'):
        a.langs = [x.strip() for x in a.langs.split(',') if x.strip()]
    return {'list': cmd_list, 'export': cmd_export, 'roundtrip': cmd_roundtrip, 'edit': cmd_edit, 'find': cmd_find,
            'glyphs': cmd_glyphs, 'refs': cmd_refs, 'names': cmd_names, 'subtitles': cmd_subtitles,
            'exe-strings': cmd_exe_strings}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
