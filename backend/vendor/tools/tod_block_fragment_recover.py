"""Recover map/mission fragments without restools cursor traversal.
Supported retail build uses CompiledAsset::field_C=0xBAADF00D. Candidate count MUST
match ResourcesTotal, and size table MUST account for the complete file. Raw builtin
properties retained. Requires an isolated local stage and keeps every fragment dump.
"""
import argparse, hashlib, json, shutil, struct
from pathlib import Path
import tod_fragment_decode as frag

def assets(source):
    d=source.read_bytes(); base=299 if source.suffix.lower()=='.map' else 0
    _,_,_,count,size,_=struct.unpack_from('<IIIiII',d,base)
    assert 0<count<100000 and base+24+size+4*count<=len(d), 'Invalid shared header'
    info=d[base+24:base+24+size]; records=[]
    for off in range(0,len(info)-28,16):
        typ,rel,_,sentinel,_,_,_=struct.unpack_from('<7I',info,off)
        nameptr=(off+4+(rel&~3))&0xffffffff
        if typ>10 or sentinel!=0xbaadf00d or nameptr>=len(info) or info[nameptr:nameptr+1]!=b'/':continue
        end=info.find(b'\0',nameptr,min(len(info),nameptr+512))
        if end<0:continue
        raw=info[nameptr:end]
        if not all(32<=c<127 for c in raw):continue
        records.append(dict(info_offset=off,type=typ,name=raw.decode('ascii')))
    assert len(records)==count, f'Asset count mismatch: {len(records)} vs {count}'
    sizes=struct.unpack_from('<'+'I'*count,d,base+24+size)
    offset=base+24+size+4*count
    assert offset+sum(sizes)==len(d), 'Payload sizes do not account for full file'
    for record,length in zip(records,sizes):
        record.update(data_offset=offset,bytes=length,payload=d[offset:offset+length]);offset+=length
    return records

def validate_chain(blob):
    assert len(blob)>=24, 'Fragment shorter than header'
    u=lambda o:struct.unpack_from('<I',blob,o)[0]
    block=u(0); seen=set(); spans=[]
    while block not in (0,0x80000000):
        assert block not in seen and block+12<=len(blob), 'Invalid/cyclic block pointer'
        seen.add(block);nxt=u(block);length=u(block+4);start=(u(block+8)+block+8)&0xffffffff
        assert start+length<=len(blob) and start>=block+12, 'Out-of-bounds record span'
        spans.append((start,start+length))
        if nxt in (0,0x80000000):break
        following=(nxt+block)&0xffffffff
        assert following>block, 'Non-forward chain'
        block=following
    assert spans, 'No blocks'
    return spans

def extract(source,stage,output):
    stage.mkdir(parents=True,exist_ok=False)
    staged=stage/source.name;shutil.copy2(source,staged)
    records=assets(staged)
    level=dict(block=source.stem,type=source.suffix[1:],fragments=[],totals={'entities':0},
               extraction={'method':'validated_asset_header_scan','source':str(source),
                           'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                           'asset_count':len(records),'payload_accounting':'exact'})
    audit=[]
    for i,r in enumerate(records):
        payload=r.pop('payload');audit.append(r)
        if r['type']!=4:continue
        assert r['name'].lower().endswith('.fragment'), r['name']
        name=r['name'].rsplit('/',1)[-1]
        dump=stage/f'{i:04d}_{name}';dump.write_bytes(payload)
        spans=validate_chain(payload)
        ops,stats=frag.decode_fragment(payload,{})
        assert stats['blocks']==len(spans) and stats['resyncs']==0 and stats['skipped_words']==0, (name,stats)
        entities=frag.build_entities(ops)
        raw={}
        for op in ops:
            if op["op"]=="create":raw[op["nodeId"]]={}
            elif op["op"]=="setprop":raw.setdefault(op["nodeId"],{})["builtin#%d"%op["propIndex"]]=op["value"]
        for entity in entities:entity["properties_raw"]=raw.get(entity["nodeId"],{})
        level['fragments'].append(dict(name=name,stats=stats,entityCount=len(entities),entities=entities,
                                       source_asset=r['name'],payload_sha256=hashlib.sha256(payload).hexdigest()))
        level['totals']['entities']+=len(entities)
    assert level['fragments'], 'No fragment assets'
    (stage/'asset_audit.json').write_text(json.dumps(audit,indent=2))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(level,indent=1))
    return level

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--stage',type=Path,required=True);p.add_argument('-o',type=Path,required=True)
    a=p.parse_args();x=extract(a.source,a.stage,a.o);print(json.dumps(x['totals']))
