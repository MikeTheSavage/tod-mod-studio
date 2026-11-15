"""For each model with collision: are hull vertices in model space or pivot-local space? Compare with render vertices."""
import sys, os, struct, collections, math
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__),'proj'))
import todblock as tb, todcoll as tc
import tod_model_extract as me, tod_model_to_gltf as g
def pivots_fixed(info, R):
    pp=tc.deref(info,R+0x30); out=[]
    for i in range(tc.i32(info,R+0x34)):
        pv=pp+i*0x7C
        out.append(dict(pos=list(struct.unpack_from('<3f',info,pv)), quat=list(struct.unpack_from('<4f',info,pv+12)), parent=tc.i32(info,pv+0x58)))
    return out
def conj(q): return [-q[0],-q[1],-q[2],q[3]]
res=collections.Counter()
for fn in sys.argv[1:]:
    d=open(fn,'rb').read(); b=tb.Block(d, os.path.splitext(fn)[1]); info=bytes(b.info)
    for k,R in enumerate(tb.record_starts(info,b.n)):
        if tc.u32(info,R)!=3: continue
        name=tb.record_name(info,R)
        m=me.extract_model(info,R,name)
        if not m: continue
        P=pivots_fixed(info,R)
        for mode in ('raw','conj'):
            PP=[dict(pos=p['pos'],quat=(p['quat'] if mode=='raw' else conj(p['quat'])),parent=p['parent']) for p in P]
            W=g.world_mats(PP)
            rv=set()
            for mesh in m['meshes']:
                M=W[mesh['pivot']]
                for v in mesh['verts']:
                    q=g.xform(M,v[0]); rv.add((round(q[0],2),round(q[1],2),round(q[2],2)))
            if mode=='raw': rv_raw=rv; W_raw=W
            else: rv_conj=rv; W_conj=W
        hulls=[]
        f=tc.deref(info,R+0x54)
        if f is not None:
            vp=tc.deref(info,f)
            for j in range(tc.i32(info,f+4)):
                sp=tc.deref(info,tc.deref(info,vp+4*j))
                if tc.u32(info,sp)==4: hulls.append(('f54',sp,tc.u32(info,sp+0x2c)&0x7f))
        pp=tc.deref(info,R+0x30)
        for i in range(tc.i32(info,R+0x34)):
            c=tc.deref(info,pp+i*0x7C+0x44)
            if c is None: continue
            vp=tc.deref(info,c)
            for j in range(tc.i32(info,c+4)):
                sp=tc.deref(info,vp+4*j)
                if tc.u32(info,sp)==4: hulls.append(('piv',sp,i))
        if not hulls or not rv_raw: continue
        sc=collections.Counter()
        for kind,sp,pi in hulls:
            h=tc.read_hull(info,sp)
            for hyp in ('model','pivraw','pivconj'):
                hit=0
                for v in h['verts']:
                    if hyp=='model': q=v; S=rv_raw
                    elif hyp=='pivraw': q=g.xform(W_raw[pi],v); S=rv_raw
                    else: q=g.xform(W_conj[pi],v); S=rv_conj
                    if (round(q[0],2),round(q[1],2),round(q[2],2)) in S: hit+=1
                sc[(kind,hyp)]+=hit
            sc[(kind,'n')]+=len(h['verts'])
        nonid=sum(1 for p in P if any(abs(x)>1e-4 for x in p['pos']) or abs(abs(p['quat'][3])-1)>1e-4)
        line="%-70s piv=%2d nonid=%2d "%(name[-70:],len(P),nonid)
        for kind in ('f54','piv'):
            n=sc[(kind,'n')]
            if n: line+=" %s n=%d model=%.2f pivraw=%.2f pivconj=%.2f"%(kind,n,sc[(kind,'model')]/n,sc[(kind,'pivraw')]/n,sc[(kind,'pivconj')]/n)
        print(line)
