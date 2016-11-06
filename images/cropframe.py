from PIL import Image
import sys
import os.path

if len(sys.argv) < 4:
    print("Usage: cropframe.py <pngImage> <cornerWidth> <cornerHeight>")
    sys.exit(1)

fn = sys.argv[1]
fnb = os.path.splitext(fn)[0]

img = Image.open(fn)
fw = int(sys.argv[2])
fh = int(sys.argv[3])

w = img.size[0]
h = img.size[1]
print(w,h)

if fw == 0:
    dx= 'c'
    x = [(0,w)]
else:
    dx= 'lcr'
    x = [(0,fw), (fw,1), (w-fw,fw)]
if fh == 0:
    dy= 'c'
    y = [(0,h)]
else:
    dy= 'ucl'
    y = [(0,fh), (fh,1), (h-fh,fh)]

verbose = True
for ix,xxx in enumerate(x):
    xx = xxx[0]
    w = xxx[1]
    for iy,yyy in enumerate(y):
        yy = yyy[0]
        h = yyy[1]
        if verbose: 
            print(xx,yy,xx+w,yy+h)
        t = img.crop((xx, yy, xx+w,yy+h))
        #apply_alpha(t, alpha*255//10, verbose)
        #t.putalpha(alpha*255//10)
        t.save(fnb + "_"+dy[iy]+dx[ix]+".png")
