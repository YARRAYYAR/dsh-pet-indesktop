from functools import lru_cache
from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap,QImage,QRegion,qRgba

@lru_cache(maxsize=8)
def masks(width,height,stride):
 bits=stride*8
 rows=((1<<(bits*height))-1)//((1<<bits)-1)
 inside=rows*((1<<width)-1)
 return inside,rows,rows<<(width-1)

def coverage_region(canvas):
 alpha=canvas.convertToFormat(QImage.Format.Format_Alpha8).convertToFormat(QImage.Format.Format_ARGB32)
 visible=alpha.createMaskFromColor(0,Qt.MaskMode.MaskOutColor)
 rgba=canvas.convertToFormat(QImage.Format.Format_ARGB32)
 floor=rgba.createMaskFromColor(qRgba(0,0,0,1),Qt.MaskMode.MaskInColor)
 visible=visible.convertToFormat(QImage.Format.Format_MonoLSB)
 floor=floor.convertToFormat(QImage.Format.Format_MonoLSB)
 width,height,stride=visible.width(),visible.height(),visible.bytesPerLine()
 inside,first,last=masks(width,height,stride)
 bits=(int.from_bytes(visible.constBits(),'little') & ~int.from_bytes(floor.constBits(),'little')) & inside
 horizontal=bits|((bits&~last)<<1)|((bits&~first)>>1)
 padded=(horizontal|(horizontal<<(stride*8))|(horizontal>>(stride*8)))&inside
 data=padded.to_bytes(stride*height,'little')
 image=QImage(data,width,height,stride,QImage.Format.Format_MonoLSB)
 image.setColorTable([0xffffffff,0xff000000])
 return QRegion(QBitmap.fromImage(image))
