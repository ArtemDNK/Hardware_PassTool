# Собирает firmware/fonts/cozette_ru.bdf из полного cozette.bdf:
#   python tools/subset_bdf.py cozette.bdf firmware/fonts/cozette_ru.bdf
# cozette.bdf: https://github.com/the-moonwitch/Cozette/releases
import sys,re
src,dst=sys.argv[1],sys.argv[2]
keep=set(range(32,127))|set(range(0x400,0x460))|{0xA0,0xAB,0xBB,0x2116,0x2022,0x2026,0x25B2,0x25BC,0x25B6,0x25C0,0x2190,0x2191,0x2192,0x2193,0x2713,0xB7,0x2013,0x2014}
txt=open(src,encoding="latin-1").read()
head,rest=txt.split("STARTCHAR",1)
chars=re.findall(r"STARTCHAR.*?ENDCHAR\n","STARTCHAR"+rest,re.S)
out=[];bb=[0,0,0,0]
minx=miny=10**9;maxx=maxy=-10**9
for c in chars:
    enc=int(re.search(r"^ENCODING (-?\d+)",c,re.M).group(1))
    if enc in keep:
        w,h,x,y=map(int,re.search(r"^BBX (-?\d+) (-?\d+) (-?\d+) (-?\d+)",c,re.M).groups())
        minx=min(minx,x);miny=min(miny,y);maxx=max(maxx,x+w);maxy=max(maxy,y+h)
        out.append(c)
head=re.sub(r"^FONTBOUNDINGBOX .*$","FONTBOUNDINGBOX %d %d %d %d"%(maxx-minx,maxy-miny,minx,miny),head,flags=re.M)
head=re.sub(r"^CHARS \d+","CHARS %d"%len(out),head,flags=re.M)
open(dst,"w",encoding="latin-1").write(head+"".join(out)+"ENDFONT\n")
print(len(out),"glyphs; bbox",maxx-minx,maxy-miny,minx,miny)
