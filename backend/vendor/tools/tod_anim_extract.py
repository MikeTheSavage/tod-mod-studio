#!/usr/bin/env python3
"""
TOD static animation -> glTF extractor (no runtime / SecuROM).

Reads .animation assets from a compiled block and emits a glTF containing the model's skeleton
(nodes/joints) plus one animation with per-bone rotation tracks (+ root translation). Bones bind
to the model skeleton by pivot index (animation pivot N drives model bone N).

Format (verified, see docs/animation_format.md):
  AnimationAsset record: +0x28 frames; +0x5C -> keyframe block (self-rel, mask ~3);
    +0x60 block u32-len; +0x64 (u16) #position-track pivots; +0x66 (u16) #orientation-track pivots.
  Keyframe block (base = +0x5C & ~3): +0 u32 header(entry count); +4 per-pivot 12-byte entries:
    e[0]=posOffset(24b)|flags(8b); e[1]=orientOffset(24b)|flags(8b); e[2]=u32 static flags
    (0x1000=pos static, 0x2000=orient static). Offsets are in 4-byte units from base.
  Position(F): o=posOffset; if !(flags&0x1000): o += field64*F*3; xyz = 3 floats @ base+o*4.
  Orient(F):  o=orientOffset; if !(flags&0x2000): o += field66*F*2; int16 q[4] @ base+o*4,
              memory order w,x,y,z; value = i16/32767 -> glTF (x,y,z,w).
"""
import struct, sys, os, json, math, argparse
import tod_model_extract as me   # reuse skeleton walk
import tod_model_to_gltf as g

FPS = 30.0

def frame_time_float32(frame, fps=FPS):
    """Encode the frame grid without crossing a glTF reader's float-quotient ceiling.

    Most times use nearest float32. A few endpoints (e.g. frame 241 at 30 Hz)
    need the immediately preceding float to avoid an unintended extra frame.
    """
    assert isinstance(frame, int) and 0 <= frame < 2**24 and fps > 0
    value = struct.unpack('<f', struct.pack('<f', frame / fps))[0]
    ratio = struct.unpack('<f', struct.pack('<f', value / (1.0 / fps)))[0]
    if ratio > frame:
        bits = struct.unpack('<I', struct.pack('<f', value))[0]
        value = struct.unpack('<f', struct.pack('<I', bits - 1))[0]
    return value

def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def i32(b,o): return struct.unpack_from('<i',b,o)[0]
def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def i16(b,o): return struct.unpack_from('<h',b,o)[0]
def f32(b,o): return struct.unpack_from('<f',b,o)[0]

def find_anim_records(info):
    recs=[]
    for p in range(0,len(info)-8,16):
        if u32(info,p)!=9: continue
        npos=me.deref(info,p+4)
        if npos is None or npos>=len(info) or info[npos:npos+1]!=b'/': continue
        nm=me.cstr(info,npos)
        if nm.lower().endswith('.animation'): recs.append((p,nm))
    return recs

def decode_anim(info, base, npivots, remap=None):
    """remap (optional): remap[model_pivot] -> keyframe-entry index. The engine reorders bones
    via a runtime table (AnimationController+0xc) — pivot P's tracks live at entry remap[P], NOT
    entry P. Without it, multi-bone humanoid skins SCRAMBLE (chicken's remap is ~identity so it
    looked fine). Captured live by the remap hook in tools/runtime_capture. See
    [[tod-static-mesh-anim-extract]]."""
    frames=i32(info, base+0x28)
    kf=me.deref(info, base+0x5C)
    f64=u16(info, base+0x64); f66=u16(info, base+0x66)
    if kf is None or frames<=0: return None
    nentry=u32(info, kf)
    nmax=nentry if 0<nentry<4096 else npivots
    tracks=[]  # per bone: {'rot':[(x,y,z,w)/frame] or None, 'pos':[(x,y,z)]/frame or None}
    for pi in range(npivots):
        ei = remap[pi] if (remap is not None and pi < len(remap)) else pi
        if ei is None or ei < 0 or ei >= nmax:
            tracks.append({'rot':None,'pos':None}); continue
        e=kf+4+ei*12
        posoff=u32(info,e)&0xFFFFFF; pflags=u32(info,e)>>24
        orioff=u32(info,e+4)&0xFFFFFF; oflags=u32(info,e+4)>>24
        sflags=u32(info,e+8)
        rot=None; pos=None
        if orioff:
            rot=[]
            for F in range(frames):
                o=orioff + (0 if (sflags&0x2000) else f66*F*2)
                a=kf+o*4
                w,x,y,z=i16(info,a)/32767.0,i16(info,a+2)/32767.0,i16(info,a+4)/32767.0,i16(info,a+6)/32767.0
                rot.append((x,y,z,w))
        if posoff:
            pos=[]
            for F in range(frames):
                o=posoff + (0 if (sflags&0x1000) else f64*F*3)
                a=kf+o*4
                pos.append((f32(info,a),f32(info,a+4),f32(info,a+8)))
        tracks.append({'rot':rot,'pos':pos})
    return {'frames':frames,'tracks':tracks}

def validate(anim):
    good=tot=0
    for t in anim['tracks']:
        if not t['rot']: continue
        for (x,y,z,w) in t['rot']:
            m=math.sqrt(x*x+y*y+z*z+w*w); tot+=1
            if abs(m-1.0)<0.03: good+=1
    return good,tot

def build_anim_gltf(pivots, anims):
    """glTF: skeleton nodes (bind pose) + one animation per clip."""
    nodes=[]
    for i,p in enumerate(pivots):
        nd={'name':p['name'] or 'bone%d'%i,
            'translation':p['pos'],'rotation':p['quat']}
        nodes.append(nd)
    for i,p in enumerate(pivots):
        ch=[j for j,q in enumerate(pivots) if q['parent']==i and j!=i]
        if ch: nodes[i]['children']=ch
    roots=[i for i,p in enumerate(pivots) if not (0<=p['parent']<len(pivots) and p['parent']!=i)]

    buf=bytearray(); bviews=[]; accs=[]
    def add(arr, comp, typ, mn=None, mx=None):
        nonlocal buf
        off=len(buf)
        if comp==5126 and typ=='SCALAR': data=struct.pack('<%df'%len(arr),*arr)
        elif typ=='VEC3': data=struct.pack('<%df'%(len(arr)*3),*[c for v in arr for c in v])
        elif typ=='VEC4': data=struct.pack('<%df'%(len(arr)*4),*[c for v in arr for c in v])
        buf+=data; buf+=b'\0'*((4-len(buf)%4)%4)
        bviews.append({'buffer':0,'byteOffset':off,'byteLength':len(data)})
        a={'bufferView':len(bviews)-1,'componentType':5126,'count':len(arr),'type':typ}
        if mn: a['min']=mn; a['max']=mx
        accs.append(a); return len(accs)-1

    gltf_anims=[]
    for clip in anims:
        nf=clip['anim']['frames']
        # Keep the binary float32 frame time and accessor bounds consistent;
        # decimal rounding can cause the importer to append an extra frame.
        times=[frame_time_float32(f) for f in range(nf)]
        tin=add(times,5126,'SCALAR',[min(times)],[max(times)])
        samplers=[]; channels=[]
        for bi,t in enumerate(clip['anim']['tracks']):
            if t['rot']:
                so=add(t['rot'],5126,'VEC4')
                samplers.append({'input':tin,'output':so,'interpolation':'LINEAR'})
                channels.append({'sampler':len(samplers)-1,'target':{'node':bi,'path':'rotation'}})
            if t['pos']:
                so=add(t['pos'],5126,'VEC3')
                samplers.append({'input':tin,'output':so,'interpolation':'LINEAR'})
                channels.append({'sampler':len(samplers)-1,'target':{'node':bi,'path':'translation'}})
        gltf_anims.append({'name':clip['name'],'samplers':samplers,'channels':channels})

    gltf={'asset':{'version':'2.0','generator':'tod_anim_extract'},
          'buffers':[{'byteLength':len(buf)}],'bufferViews':bviews,'accessors':accs,
          'nodes':nodes,'scenes':[{'nodes':roots}],'scene':0,'animations':gltf_anims}
    return gltf, bytes(buf)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('block'); ap.add_argument('model', help='model name substring (for the skeleton)')
    ap.add_argument('-o','--out', default=None)
    args=ap.parse_args()
    info=me.load_info(args.block)
    # skeleton from the model
    mrec=next(((b,n) for b,n in me.find_model_records(info) if args.model.lower() in n.lower()), None)
    if not mrec: sys.exit('model not found: '+args.model)
    model=me.extract_model(info,*mrec)
    pivots=model['pivots']; npiv=len(pivots)
    print('skeleton %r: %d pivots'%(model['name'],npiv))
    # animations whose name shares the model's stem (e.g. chicken_*.animation)
    stem=os.path.splitext(os.path.basename(model['name']))[0].lower()
    clips=[]
    for b,n in find_anim_records(info):
        an=os.path.splitext(os.path.basename(n))[0]
        if not an.lower().startswith(stem): continue
        a=decode_anim(info,b,npiv)
        if not a: continue
        gd,tt=validate(a)
        clips.append({'name':an,'anim':a})
        print('  %-36s frames=%d  unit-quat %d/%d'%(an,a['frames'],gd,tt))
    if not clips: sys.exit('no matching animations')
    gltf,blob=build_anim_gltf(pivots,clips)
    out=args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),'out',stem+'.anim.glb')
    os.makedirs(os.path.dirname(out),exist_ok=True)
    g.write_glb(out,gltf,blob)
    print('wrote %s : %d clips, %d bones'%(out,len(clips),npiv))

if __name__=='__main__': main()
