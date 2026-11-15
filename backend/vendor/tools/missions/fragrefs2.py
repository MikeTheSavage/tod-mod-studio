import collections, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import todblock as tb, fragedit as fe, fragtool as ft
arch = ft.archive(); T = ft.types()
pat = sys.argv[1].lower()
for nm in sorted(arch.names):
    if os.path.splitext(nm)[1].lower() not in tb.BLOCK_EXTS or ('/shared/' not in nm): continue
    raw, entry, ext = ft.load_block_bytes(nm); b = tb.Block(raw, ext); frs, _ = ft.fragments(b)
    for k, fnm in frs:
        doc = fe.FragDoc(b.payloads[k], T, fnm)
        for n in doc.created_ids():
            f = doc.get(n, 'fragment', None)
            if f and pat in f.lower():
                print(entry.rsplit('/',1)[-1], fnm.rsplit('/',1)[-1], '0x%08X' % n, doc.path_of(n), doc.type_of(n), f)
