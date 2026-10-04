import hashlib,json,sys,time
from pathlib import Path
import psutil
from PySide6.QtCore import QCoreApplication,QTimer
from pet.config import Config
from pet.settings_commands import SettingsCommandClient
p=psutil.Process(57857)
cfg=Config();before=hashlib.sha256(cfg.path.read_bytes()).hexdigest()
app=QCoreApplication([]);client=SettingsCommandClient(cfg);responses=[]
def received(r):responses.append(r);app.quit()
client.request('quit',{},received);QTimer.singleShot(10000,app.quit);app.exec()
assert responses and responses[0]['ok']
p.wait(15)
assert before==hashlib.sha256(cfg.path.read_bytes()).hexdigest()
Path('docs/evidence/seeky6-performance/continuation/installed-quit.json').write_text(json.dumps({'command':[sys.executable,str(Path(__file__).resolve())],'setup':'Normal quit of exact installed primary launched by this task, before isolated Cocoa measurement','inputs':{'pid':57857,'command':'quit'},'assertions':'Acknowledged; process exits; config unchanged','checks':{'ack':responses,'config_unchanged':True},'exit_status':0,'reset':'Reopen installed primary after measurement/delivery'},indent=2)+'\n')
