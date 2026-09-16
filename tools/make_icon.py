from pathlib import Path
from PIL import Image, ImageDraw
BG='#0a0f14'; A='#f0b84a'; B='#77c8ff'
def rgb(h):
    h=h.lstrip('#'); return tuple(int(h[i:i+2],16) for i in (0,2,4))+(255,)
img=Image.new("RGBA",(256,256),rgb(BG)); d=ImageDraw.Draw(img); A=rgb(A); B=rgb(B)
d.line((48,62,48,194),fill=(73,91,105,255),width=14); d.line((208,62,208,194),fill=(73,91,105,255),width=14); d.line((48,78,82,78,112,104,152,128,208,128),fill=A,width=16,joint='curve'); d.line((48,178,82,178,112,152,152,128),fill=(255,124,85,255),width=16,joint='curve'); d.ellipse((34,64,62,92),fill=(119,200,255,255)); d.ellipse((34,164,62,192),fill=(255,124,85,255)); d.ellipse((194,114,222,142),fill=(245,215,124,255))
out=Path(__file__).resolve().parents[1]/"assets"/"icon.ico"
out.parent.mkdir(exist_ok=True)
img.save(out,format="ICO",sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(out)