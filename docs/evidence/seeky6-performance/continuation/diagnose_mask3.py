import sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'scripts')]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QRegion,QBitmap,qRgba
from PySide6.QtCore import Qt,QPoint
from compare_seeky_quality import first_frame
from pet.frame_edges import coverage_region
from mask_candidate_3 import coverage_region as candidate,masks
app=QApplication([])
src=first_frame(Path('assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm'))
c=src.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(832,468,Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
a=c.convertToFormat(QImage.Format.Format_Alpha8).convertToFormat(QImage.Format.Format_ARGB32)
v=a.createMaskFromColor(0,Qt.MaskOutColor)
f=c.convertToFormat(QImage.Format.Format_ARGB32).createMaskFromColor(qRgba(0,0,0,1),Qt.MaskInColor)
for m in v,f:m.setColorTable([0xffffffff,0xff000000])
print('formats',v.format(),f.format(),'strides',v.bytesPerLine(),f.bytesPerLine(),'dim',v.size(),f.size())
for m in v,f:
 n=m.convertToFormat(QImage.Format.Format_MonoLSB)
 print('conversion region equal',QRegion(QBitmap.fromImage(m))==QRegion(QBitmap.fromImage(n)),'palette',n.colorTable())
 print('firstbits',bytes(m.constBits())[:30].hex(),bytes(n.constBits())[:30].hex())
r=coverage_region(c);s=candidate(c)
print('bounds',r.boundingRect(),s.boundingRect(),'rectcount',r.rectCount(),s.rectCount(),'diffbounds',(r^s).boundingRect())
vv=v.convertToFormat(QImage.Format.Format_MonoLSB);ff=f.convertToFormat(QImage.Format.Format_MonoLSB)
stride=vv.bytesPerLine();inside,first,last=masks(c.width(),c.height(),stride)
b=(int.from_bytes(vv.constBits(),'little')&~int.from_bytes(ff.constBits(),'little'))&inside
reg=QRegion(QBitmap.fromImage(v))-QRegion(QBitmap.fromImage(f))
h=b|((b&~last)<<1)|((b&~first)>>1)
d=(h|(h<<(stride*8))|(h>>(stride*8)))&inside
for y in range(c.height()):
 for x in range(c.width()):
  p=QPoint(x,y);bb=bool(b&(1<<(y*stride*8+x)));dd=bool(d&(1<<(y*stride*8+x)))
  if reg.contains(p)!=bb or r.contains(p)!=dd or s.contains(p)!=dd:
   print('firstdiff',x,y,'base',reg.contains(p),bb,'padded',r.contains(p),dd,'result',s.contains(p),'sourceRGBA',hex(c.pixel(x,y)))
   raise SystemExit(0)
