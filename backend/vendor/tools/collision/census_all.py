"""Census of every collision shape in every block of blocks.naz (read-only)."""
import sys, os, struct, collections, json
sys.path.insert(0, os.path.dirname(__file__))
import todblock as tb
u32=tb.u32; i32=tb.i32
def deref(info, fa):
    v=u32(info,fa)
    if v==0 or v==0x80000000: return None
    return (fa+(v&~3))&0xFFFFFFFF
arch=tb.Archive(os.environ.get('TOD_NAZ', r"C:\GOG Games\Total Overdose\blocks.naz"))
C=collections.Counter(); ex={}
def note(k, v=None):
    C[k]+=1
    if v is not None and k not in ex: ex[k]=v
def shape(info, sp, where):
    t=u32(info,sp); note(('type',t))
    note(('flags20',hex(u32(info,sp+0x20)>>24), t))
    note(('surf24',hex(u32(info,sp+0x24)), t))
    if t==4:
        w=u32(info,sp+0x2c); nv=(w>>8)&0xff; bits=(w>>16)&0xf; ne=w>>20
        note(('pivbyte', w&0xff))
        note(('nv', nv)); note(('bits_ok', bits == max(1,(nv).bit_length()) ))
        note(('x34', u32(info,sp+0x34)!=0), where); note(('x38', u32(info,sp+0x38)!=0), where)
        note(('x28', u32(info,sp+0x28)!=0), where)
        a=deref(info,sp+0x50)
        if a is None: note(('aux','none'))
        else:
            for vo in (0,0x24,0x34,0x44):
                note(('auxvec',vo,i32(info,a+vo+4)!=0), where)
            note(('auxhdr',hex(u32(info,a+0x10)),hex(u32(info,a+0x20))))
        fm=i32(info,sp+0x40); 
        # count terminators
        p=deref(info,sp+0x4c); data=info[p:p+((bits*ne+7)>>3)+4]
        val=int.from_bytes(data,'little'); term=(1<<bits)-1
        idx=[(val>>(bits*k))&term for k in range(ne)]
        nf=sum(1 for x in idx if x==term)
        note(('facemats==nfaces', fm==nf), where if fm!=nf else None)
        sizes=[]; cur=0
        for x in idx:
            if x==term: sizes.append(cur); cur=0
            else: cur+=1
        for s in sizes: note(('polysize',s))
        note(('ends_with_term', idx[-1]==term if idx else None))
        note(('maxidx<nv', max([x for x in idx if x!=term] or [0])<nv))
    elif t==1:
        note(('box',))
    else:
        note(('othertype',t), where)
blocks=[n for n in arch.names if os.path.splitext(n)[1] in tb.BLOCK_EXTS]
nb=0
for name in sorted(blocks):
    try:
        b=tb.Block(arch.read(name), os.path.splitext(name)[1]); info=bytes(b.info)
        starts=tb.record_starts(info,b.n)
    except Exception as e:
        note(('blockerr',str(e)[:40]), name); continue
    nb+=1
    for k,R in enumerate(starts):
        if u32(info,R)!=3: continue
        note(('model',))
        pp=deref(info,R+0x30); pc=i32(info,R+0x34)
        for i in range(pc):
            pv=pp+i*0x7C
            c=deref(info,pv+0x44)
            note(('surfprops_count', i32(info,pv+0x38)>0), (name,k,i) )
            if c is None: continue
            note(('pivlist_hdr10',hex(u32(info,c+0x10))))
            vp=deref(info,c); vc=i32(info,c+4)
            note(('pivlist_vec', hex(u32(info,c+0xc))))
            for j in range(vc):
                shape(info, deref(info,vp+4*j), (name,k,i,j))
        f=deref(info,R+0x54)
        if f is not None:
            note(('f54',)); note(('f54_10', u32(info,f+0x10)))
            vp=deref(info,f); vc=i32(info,f+4)
            for j in range(vc):
                el=deref(info,vp+4*j)
                note(('wrapper_zero', info[el+4:el+0x1c]==bytes(24)))
                shape(info, deref(info,el), (name,k,'f54',j))
print("blocks", nb)
for k,v in sorted(C.items(), key=lambda x: str(x[0])):
    print(k, v, ex.get(k,''))
