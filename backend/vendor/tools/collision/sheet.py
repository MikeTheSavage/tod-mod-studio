"""sheet.py OUT.png TITLE 'label line|label line|dir|i,i,i' ... - rows of frames (one row per run) with labels, frame time stamps."""
import sys, json, os
from PIL import Image, ImageDraw, ImageFont
out, title, rows = sys.argv[1], sys.argv[2], sys.argv[3:]
try:
    font = ImageFont.truetype("arial.ttf", 22); small = ImageFont.truetype("arial.ttf", 16)
except Exception:
    font = small = ImageFont.load_default()
W, H, LW = 480, 360, 300
parsed = []
for r in rows:
    parts = r.split('|'); lab = '\n'.join(parts[:-2]); d, idx = parts[-2], [int(x) for x in parts[-1].split(',')]
    parsed.append((lab, d, idx))
ncol = max(len(p[2]) for p in parsed)
img = Image.new('RGB', (LW + ncol * W, 40 + len(parsed) * (H + 26)), (18, 18, 22))
dr = ImageDraw.Draw(img)
dr.text((10, 8), title, fill=(255, 255, 255), font=font)
for ri, (lab, d, idx) in enumerate(parsed):
    y = 40 + ri * (H + 26)
    for li, part in enumerate(lab.split('\n')):
        dr.text((10, y + 10 + li * 24), part, fill=(255, 220, 120), font=font if li == 0 else small)
    times = json.load(open(os.path.join(d, 'frames.json')))['times']
    for ci, i in enumerate(idx):
        im = Image.open(os.path.join(d, 'f%04d.png' % i)).resize((W, H))
        img.paste(im, (LW + ci * W, y))
        dr.text((LW + ci * W + 6, y + H + 2), 't = %.1f s' % times[i], fill=(200, 200, 200), font=small)
img.save(out)
print(out, img.size)
