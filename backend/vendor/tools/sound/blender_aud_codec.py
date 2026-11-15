"""Runs INSIDE Blender (background): Ogg Vorbis encode / decode through Blender's Audaspace (aud, FFmpeg build).

  blender -b --factory-startup --python blender_aud_codec.py -- --result R.json --jobs JOBS.json

JOBS.json: [{"op": "encode", "in": "x.wav", "out": "x.ogg", "rate": 44100, "channels": 1, "bitrate": 80000},
            {"op": "decode", "in": "x.ogg", "out": "x.wav"}]
Started by sound_tool.py (run_blender); never run against files inside the game folder.
"""
import sys
import json
import os
import traceback

argv = sys.argv[sys.argv.index('--') + 1:]
res = argv[argv.index('--result') + 1]
jobs = json.load(open(argv[argv.index('--jobs') + 1]))
out = {'ok': False, 'done': []}
try:
    import aud
    for j in jobs:
        s = aud.Sound(j['in'])
        ch = aud.CHANNELS_MONO if int(j.get('channels', s.specs[1])) == 1 else aud.CHANNELS_STEREO
        rate = int(j.get('rate', s.specs[0]))
        if j['op'] == 'encode':
            if int(s.specs[0]) != rate:
                s = s.resample(rate, False)
            s.write(j['out'], rate=rate, channels=ch, format=aud.FORMAT_FLOAT32, container=aud.CONTAINER_OGG,
                    codec=aud.CODEC_VORBIS, bitrate=int(j.get('bitrate', 80000)), buffersize=4096)
        elif j['op'] == 'decode':
            s.write(j['out'], rate=rate, channels=ch, format=aud.FORMAT_S16, container=aud.CONTAINER_WAV,
                    codec=aud.CODEC_PCM)
        else:
            raise ValueError('unknown op ' + j['op'])
        out['done'].append({'op': j['op'], 'in': j['in'], 'out': j['out'], 'bytes': os.path.getsize(j['out']),
                            'in_specs': list(s.specs)})
    out['ok'] = True
except Exception:
    out['tb'] = traceback.format_exc()
json.dump(out, open(res, 'w'), indent=1)
