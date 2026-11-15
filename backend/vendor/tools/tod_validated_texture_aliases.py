"""Exact-reference aliases for valid source filenames unsupported by Google Drive."""
import json,hashlib
from pathlib import Path
_cache=None
def resolve_validated_alias(reference):
 global _cache
 if _cache is None:
  index=Path(__file__).resolve().parent/'out/validated_texture_aliases.json'
  _cache=json.loads(index.read_text()) if index.exists() else {}
 item=_cache.get(reference.lower()) if reference else None
 if not item:return None
 p=Path(item['path']);d=p.read_bytes()
 if hashlib.sha256(d[128:]).hexdigest()!=item['payload_sha256']:raise ValueError('Validated texture alias payload changed: '+str(p))
 return str(p)
