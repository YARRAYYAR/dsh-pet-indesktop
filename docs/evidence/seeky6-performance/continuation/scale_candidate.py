import hashlib,json,sys,time,statistics
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'scripts')]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtCore import Qt
from compare_seeky_quality import first_frame
app=QApplication([])
assert app.platformName()=='cocoa'
rows=[]
for name in ['idle/待机呼吸休闲.webm','acts/余额-分文不剩.webm']:
 path=Path('assets/characters_hq/shenshen/videos')/name
 if not path.exists():continue
 image=QPixmap.fromImage(first_frame(path)).toImage()
 for width in [317,832,1664,2304]:
  height=round(width*9/16)
  def old():return image.mirrored(True,False).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(width,height,Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
  def new():return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(width,height,Qt.IgnoreAspectRatio,Qt.SmoothTransformation).mirrored(True,False)
  a,b=old(),new()
  checks={'clip':name,'width':width,'height':height,'equal':bytes(a.constBits())==bytes(b.constBits())}
  for label,fn in [('old',old),('new',new)]:
   ts=[]
   for _ in range(40):
    t=time.perf_counter();fn();ts.append((time.perf_counter()-t)*1000)
   checks[label+'_median_ms']=statistics.median(ts)
  rows.append(checks)
output={'command':[sys.executable,str(Path(__file__).resolve())],'cwd':str(Path.cwd()),'setup':'Cocoa Qt real HQ QPixmap.toImage, before/after mirror order only','inputs':'40 repetitions at317/832/1664/2304 physical widths','assertions':'All scaled image bytes equal; timing compared','checks':rows,'exit_status':int(not all(r['equal'] for r in rows)),'reset':'Generators closed; product source unchanged'}
Path(__file__).with_suffix('.json').write_text(json.dumps(output,indent=2)+'\n');print(rows)
raise SystemExit(output['exit_status'])
