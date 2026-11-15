#!/usr/bin/env python3
"""
Extract CompiledTextureAsset records from any TOD asset block (.main/.submap/.mission/.map/...)
to .dds, in pure Python. Faithful port of restools AssetBlockReader::CompiledTextureAsset::DumpData
(restools itself SEGFAULTS on .submap/.mission, so the NPC character textures that live in mission
blocks can only be recovered this way).

*** BYTE-CORRECT (validated 2026-06-18: 514/514 textures byte-identical to restools on
overdose.main via tools/_validate_texextract.py). ***
Each asset is walked with its EXACT per-type SkipSpecificData so the sequential asset index stays
aligned with the sizes[]/data-buffer table (no heuristic drift). THE KEY CONSTANT: the engine's
serialized list (READ_LIST_VALUE) is 16 bytes {ptr,count,cap,+4}, NOT 12 — wrong stride shifts every
list-containing record (MODEL/ANIMATION/TEXT) and drifts all downstream pixel data. Per-type record
end (then ALIGN_16):
  TEXTURE  : max(TextureInfo+0x54, GfxTexture+0x2C)
  MODEL    : field_58 + *field_58 if field_58>field_54 else field_54   (field_54@+0x54, field_58@+0x58)
  ANIMATION: max(field_5C+4*field_60, List_1+24*c1, List_2+52*c2, List_3+c3)  (lists @+0x2C/+0x3C/+0x4C)
  FRAGMENT : FragmentInfo+12 if inline (within +0x10000) else after-name
  (FONT/TEXT/SOUND/STREAMEDSOUND not present in overdose.main → fall back to after-name + resync.)

Block layout (little-endian):
  [24B AssetHeaderShared: timestamp u32, propCk u32, cmdCk u32, ResourcesTotal i32,
                          AssetsHeaderSize u32, MaxBufferSize u32]
  [info buffer: AssetsHeaderSize bytes]               <- compiled asset records (sequential)
  [sizes table: ResourcesTotal * i32]                 <- per-asset data-buffer size
  [data buffers: concatenated, sizes[i] bytes each]   <- raw texture surface bits, indexed by asset i

Asset record (self-relative ptr: abs = field_off + u32@field_off):
  CompiledAsset base (0x1C): type u32@0, Name ptr@0x04, GlobalId@0x08, field_C@0x0C, ts u64@0x10, Flags@0x18
  CompiledTextureAsset adds: m_BitsPerPixel@0x1C, m_TextureInfo ptr@0x20, field_24@0x24,
                             m_GfxTexture ptr@0x28, field_2C@0x2C
  GfxTexture: SurfaceSize[0]=w @+0x14, [1]=h @+0x18, m_Format i32 @+0x1C, m_MipMapLevels u8 @+0x28

The asset stream is walked sequentially; after each record we resync to the next 16-aligned record
header (restools' LooksLikeAssetHeader heuristic) to keep the asset index aligned with sizes[i].
"""
import sys, os, struct, glob, argparse

TEXTURE = 0; MESHCOLOR = 10
FORMATS = ["R8G8B8","A8R8G8B8","R5G6B5","A1R5G5B5","A4R4G4B4","P8","UNKNOWN","DXT1","DXT2","DXT3","DXT4","DXT5"]
OUTROOT = os.path.join(os.environ.get('TOD_PROJECT', ''), 'TODPrototype', 'Content', 'Textures')   # TOD_PROJECT: the author's TOD Project folder

def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def i32(b,o): return struct.unpack_from('<i',b,o)[0]

def cstr(b,o,n=256):
    if o<0 or o>=len(b): return ''
    return b[o:o+n].split(b'\0',1)[0].decode('latin-1','replace')

def ptr(info,off):
    """self-relative pointer (restools READ_FIELD_VALUE_POINTER: abs = off + *off)."""
    if off+4>len(info): return None
    return (off + u32(info,off)) & 0xFFFFFFFF

def looks_like_header(info,p):
    n=len(info)
    if p<0 or p+8>n: return False
    if u32(info,p)>MESHCOLOR: return False
    name=p+4+u32(info,p+4)
    if name<0 or name>=n-1: return False
    return info[name]==0x2F and 0x20<=info[name+1]<0x7F   # '/' + printable

def dds_header(w,h,fmt,mips,filesize):
    DDSD=0x1|0x2|0x4|0x1000|(0x8 if fmt==1 else 0x80000)
    pitch=4 if fmt==1 else filesize
    pf_flags=(0x40|0x1) if fmt==1 else 0x4
    fourcc=b'\0\0\0\0' if fmt==1 else (FORMATS[fmt].encode('ascii')+b'\0\0\0\0')[:4]
    rgb=32 if fmt==1 else 0
    rm,gm,bm,am=(0x00ff0000,0x0000ff00,0x000000ff,0xFF000000) if fmt==1 else (0,0,0,0)
    hd =struct.pack('<7I',124,DDSD,h,w,pitch,0,mips)
    hd+=b'\0'*44
    hd+=struct.pack('<2I',32,pf_flags)+fourcc+struct.pack('<5I',rgb,rm,gm,bm,am)
    hd+=struct.pack('<5I',0x1000,0,0,0,0)
    assert len(hd)==124,len(hd)
    return b'DDS '+hd

def load_block(path):
    d=open(path,'rb').read()
    ts,pck,cck,total,infosz,maxbuf=struct.unpack_from('<IIIiII',d,0)
    if not (0<total<100000 and 0<infosz<len(d)): raise ValueError('not an asset block')
    info=d[24:24+infosz]
    sz_off=24+infosz
    sizes=list(struct.unpack_from('<%di'%total,d,sz_off))
    data_off=sz_off+total*4
    bufs=[]; o=data_off
    for s in sizes:
        bufs.append((o,s)); o+=max(0,s)
    return d,info,total,sizes,bufs

def extract(path, outroot=OUTROOT, want=None, dry=False, verbose=False, listonly=False, collect=None):
    d,info,total,sizes,bufs=load_block(path)
    nlen=len(info)
    a16=lambda x:(x+15)&~15
    a4=lambda x:(x+3)&~3
    def lp(off):  # self-relative pointer abs = off + u32@off  (restools READ_FIELD_VALUE_POINTER)
        return (off+u32(info,off))&0xFFFFFFFF if 0<=off and off+4<=nlen else None
    cur=0; n_tex=0; written=[]
    for i in range(total):
        if cur<0 or cur+8>nlen: break
        atype=u32(info,cur)
        if atype>MESHCOLOR: break
        name_abs=(cur+4+u32(info,cur+4))&0xFFFFFFFF
        name=cstr(info, name_abs)
        name_end=a4(name_abs+len(name)+1) if 0<=name_abs<nlen else cur+0x2C
        # --- exact per-type SkipSpecificData port (keeps asset index i aligned with sizes[i]) ---
        end=None
        if atype==TEXTURE:
            ti=lp(cur+0x20); gfx=lp(cur+0x28)
            if gfx is not None and gfx+0x29<=nlen:
                w=u32(info,gfx+0x14); h=u32(info,gfx+0x18); fmt=i32(info,gfx+0x1C); mips=info[gfx+0x28]
                boff,bsz=bufs[i] if i<len(bufs) else (0,0)
                ok = 0<w<=8192 and 0<h<=8192 and 0<=fmt<len(FORMATS) and bsz>0
                if listonly or verbose:
                    print("  [%3d] %-52s %dx%d %s mips=%d data=%d %s"%(
                        i,name,w,h,FORMATS[fmt] if 0<=fmt<len(FORMATS) else '?%d'%fmt,mips,bsz,'' if ok else '<<skip'))
                if ok and collect is not None:
                    collect(name, w, h, fmt, d[boff:boff+bsz])
                if ok and not listonly and (want is None or want.lower() in name.lower()):
                    rel=os.path.splitext(name.lstrip('/'))[0]+'.dds'
                    outp=os.path.join(outroot,rel)
                    if not dry:
                        os.makedirs(os.path.dirname(outp),exist_ok=True)
                        open(outp,'wb').write(dds_header(w,h,fmt,mips,bsz)+d[boff:boff+bsz])
                    written.append(rel)
                n_tex+=1
                if ti is not None: end=a16(max(ti+0x54, gfx+0x2C))
        elif atype==3:  # MODEL: end = max(field_54, field_58 + *field_58). LIST stride = 16 bytes
            # (ptr,count,cap,+4) so after field_1C(4)+2 lists(32)+phys ptr(4)+bound vec4(16):
            # field_54 @+0x54, field_58 @+0x58.
            f54=lp(cur+0x54); f58=lp(cur+0x58)
            if f54 is not None and f58 is not None:
                base=(f58+u32(info,f58)) if (f58>f54 and f58+4<=nlen) else f54
                end=a16(base&0xFFFFFFFF)
        elif atype==9:  # ANIMATION: furthest of pivot block + 3 lists (LIST stride 16)
            # field_1C/20/LoopMode/field_28 (16) + List_1@0x2C + List_2@0x3C + List_3@0x4C + field_5C@0x5C
            l1=lp(cur+0x2C); c1=u32(info,cur+0x30); l2=lp(cur+0x3C); c2=u32(info,cur+0x40)
            l3=lp(cur+0x4C); c3=u32(info,cur+0x50); f5c=lp(cur+0x5C); f60=u32(info,cur+0x60)
            if None not in (l1,l2,l3,f5c):
                fur=f5c+4*f60
                if 0<c1<1e6: fur=max(fur, l1+24*c1)
                if 0<c2<1e6: fur=max(fur, l2+52*c2)
                if 0<c3<1e7: fur=max(fur, l3+c3)
                end=a16(fur&0xFFFFFFFF)
        elif atype==4:  # FRAGMENT: inline FragmentData only if FragmentInfo points just ahead
            finfo=lp(cur+0x20); e=name_end
            if finfo is not None and cur<=finfo<cur+0x10000: e=finfo+12
            end=a16(e)
        elif atype==2:  # TEXT: 3 lists (stride16) in arbitrary order; furthest + its element bytes
            l1=lp(cur+0x20); c1=u32(info,cur+0x24); ti=lp(cur+0x30); cti=u32(info,cur+0x34)
            l3=lp(cur+0x40); c3=u32(info,cur+0x44)
            if None not in (l1,ti,l3):
                m=max(l1,ti,l3)
                e=l1+4*c1 if m==l1 else (ti+2*cti if m==ti else l3+c3)
                end=a16(e&0xFFFFFFFF)
        # MOVIE(5)/CUTSCENE(6)/MESHCOLOR(10): restools builds no record — resync from cur+16
        # (NOT from the name string, which these may not lay out normally). Anything else with an
        # unresolved end falls back to after-name.
        if end is None or end<=cur or end>nlen:
            end = a16(cur+16) if atype in (5,6,10) else a16(name_end)
        if end<nlen and looks_like_header(info,end):
            cur=end; continue
        # precise skip slightly off (or unhandled type): resync forward to next header (restools cap 0x10000)
        scan=end; cap=min(nlen, end+0x10000)
        while scan<cap and not looks_like_header(info,scan): scan+=16
        if not (scan<nlen and scan<cap and looks_like_header(info,scan)): break
        cur=scan
    return n_tex, written

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('path', help='block file OR directory to scan recursively')
    ap.add_argument('-o','--outroot', default=OUTROOT)
    ap.add_argument('-f','--filter', default=None, help='only textures whose name contains this')
    ap.add_argument('--list', action='store_true', help='list texture records, do not write')
    ap.add_argument('--dry', action='store_true', help='resolve but do not write files')
    ap.add_argument('-v','--verbose', action='store_true')
    a=ap.parse_args()
    LANG=('_es.','_de.','_it.','_fr.','_uk.','/es/','/de/','/it/','/fr/','/uk/')
    if os.path.isdir(a.path):
        blocks=[]
        for ext in ('*.main','*.submap','*.mission','*.map'):
            blocks+=glob.glob(os.path.join(a.path,'**',ext),recursive=True)
        blocks=[b for b in blocks if not any(l in b.replace(chr(92),'/').lower() for l in LANG)]
    else:
        blocks=[a.path]
    total_tex=0; total_w=0; allw=set()
    for b in blocks:
        try:
            nt,w=extract(b,a.outroot,a.filter,a.dry,a.verbose,a.list)
        except Exception as e:
            if a.verbose: print("  ERR %s: %s"%(os.path.basename(b),e))
            continue
        if nt or w:
            print("%-50s textures=%d written=%d"%(os.path.basename(b),nt,len(w)))
        total_tex+=nt; total_w+=len(w); allw|=set(w)
    print("\nTOTAL: %d texture records, %d files written (%d unique)"%(total_tex,total_w,len(allw)))

if __name__=='__main__':
    main()
