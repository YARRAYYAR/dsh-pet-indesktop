from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap,QImage,QRegion,qRgba

def coverage_region(canvas):
 alpha=canvas.convertToFormat(QImage.Format.Format_Alpha8)
 alpha.reinterpretAsFormat(QImage.Format.Format_Indexed8)
 alpha.setColorTable([0xffffffff]+[0xff000000]*255)
 visible=alpha.convertToFormat(QImage.Format.Format_MonoLSB,Qt.ImageConversionFlag.ThresholdDither)
 floor=canvas.createMaskFromColor(qRgba(0,0,0,1),Qt.MaskMode.MaskInColor)
 for mask in (floor,):
  mask.setColor(0,0xffffffff)
  mask.setColor(1,0xff000000)
 region=QRegion(QBitmap.fromImage(visible))-QRegion(QBitmap.fromImage(floor))
 padded=QRegion(region)
 for dx,dy in ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)):
  padded|=region.translated(dx,dy)
 return padded.intersected(QRegion(canvas.rect()))
