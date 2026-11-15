"""Compact tree view of fragments (mission research helper).

  python mtree.py <block> [fragment-substring ...] [--all] [--full] [-o out.txt]

Prints every entity as an indented line: name [type] node, followed by its non-boilerplate properties
(name=value). --full prints the boilerplate Node properties too. Entity values are shown as
'->name(0xID)' when they resolve inside the fragment.
"""
import argparse, os, sys, struct
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft

BOILER = {'block_id', 'script_priority', 'order', 'renderordergroup', 'parent', 'disable_on_cutscene', 'flags',
          'use_aux_quadtree', 'name', 'lod_threshold', 'fade_threshold', 'slow_fade', 'traverse_distance',
          'unique_id0', 'unique_id1', 'UserType'}


def fmt(v, t, doc):
    if t == 'Entity':
        if v is None or v == 0xFFFFFFFF:
            return 'none'
        if v == 0:
            return 'owner'
        nm = doc.get(v, 'name') if v in doc.created_ids() else None
        return '->%s(0x%08X)' % (nm, v)
    if isinstance(v, float):
        return ('%.4f' % v).rstrip('0').rstrip('.') if v == v else 'nan'
    if isinstance(v, (list, tuple)):
        if t.lower().startswith('list(entity'):
            return '[' + ', '.join(fmt(x, 'Entity', doc) for x in v) + ']'
        return '[' + ', '.join(fmt(x, '', doc) for x in v) + ']'
    if isinstance(v, str):
        return repr(v)
    return str(v)


def tree(doc, full=False, out=print):
    T = doc.T
    ids = doc.created_ids()
    kids = {}
    roots = []
    for n in ids:
        p = doc.get(n, 'parent', 0)
        if p and p in ids:
            kids.setdefault(p, []).append(n)
        else:
            roots.append(n)

    def key(n):
        o = doc.get(n, 'order', 0)
        return (o if isinstance(o, int) else 0)

    def walk(n, d):
        nm = doc.get(n, 'name', '')
        out('%s%s [%s] 0x%08X' % ('  ' * d, nm, doc.type_of(n), n))
        for r in doc.sets_of(n):
            pn = T.name(r.prop)
            if not full and pn in BOILER:
                continue
            v = doc.frag.value(r)
            if not full and pn in ('pos', 'orient') and all(abs(x) < 1e-9 for x in v[:3]):
                continue
            out('%s    %s = %s' % ('  ' * d, pn, fmt(v, T.ptype(r.prop), doc)))
        for c in sorted(kids.get(n, []), key=key):
            walk(c, d + 1)

    for r in roots:
        walk(r, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('block')
    ap.add_argument('frags', nargs='*')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('-o')
    a = ap.parse_args()
    raw, entry, ext = ft.load_block_bytes(a.block)
    b = tb.Block(raw, ext)
    frs, _ = ft.fragments(b)
    lines = []
    out = lines.append
    sel = frs if (a.all or not a.frags) else [ft.pick_fragment(frs, s) for s in a.frags]
    for k, nm in sel:
        doc = fe.FragDoc(b.payloads[k], ft.types(), nm)
        out('=== %s  (record %d, %d B, %d entities)' % (nm, k, len(b.payloads[k]), len(doc.created_ids())))
        tree(doc, a.full, out)
    text = '\n'.join(lines) + '\n'
    if a.o:
        open(a.o, 'w', encoding='utf-8').write(text)
        print('wrote', a.o, len(lines), 'lines')
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
