import hashlib,json,os,plistlib,subprocess,time
from pathlib import Path
import psutil
from pet.config import Config

source=Path('/Users/ray/Library/Caches/dsr-pet-build/macos/seeky· pet.app')
target=Path('/Users/ray/Applications/seeky· pet.app')
backup=Path('/Users/ray/Library/Caches/seeky-pet-backups')/time.strftime('seeky.6-before-mask-%Y%m%d-%H%M%S.app')
staged=target.with_name('.seeky-v6-install.app')
assert source.exists() and target.exists() and not backup.exists() and not staged.exists()
for proc in psutil.process_iter(['pid','cmdline']):
    cmd=proc.info['cmdline'] or []
    assert not any(str(p).startswith(str(target/'Contents/MacOS')) or str(p).startswith(str(source/'Contents/MacOS')) for p in cmd), f'Preserve running process {proc.pid}'
cfg=Config();assert not (cfg.dir/'settings.lock').exists(),'Existing settings window must be preserved'
config_before=hashlib.sha256(cfg.path.read_bytes()).hexdigest()
old_binary=hashlib.sha256((target/'Contents/MacOS/seeky· pet').read_bytes()).hexdigest()
backup.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['cp','-cR',str(source),str(staged)],check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(staged)],check=True)
try:
 target.rename(backup)
 staged.rename(target)
except BaseException:
 if not target.exists() and backup.exists():
  backup.rename(target)
 raise
assert old_binary==hashlib.sha256((backup/'Contents/MacOS/seeky· pet').read_bytes()).hexdigest()
assert config_before==hashlib.sha256(cfg.path.read_bytes()).hexdigest()
info=plistlib.loads((target/'Contents/Info.plist').read_bytes());assert info['CFBundleVersion']=='4.2.1.6'
result={'command':['PYTHONPATH=.','.venv/bin/python',str(Path(__file__).resolve())],'source':str(source),'installed':str(target),'backup':str(backup),'setup':'No installed/cache pet/settings process running; signed verified cache bundle; exact original app moved intact to backup; APFS clone staged then renamed','assertions':'Original retained, new version4.2.1.6, no user Config byte changed by installation','checks':{'old_binary_sha256':old_binary,'config_unchanged':True,'bundle_version':info['CFBundleVersion']},'reset':'Original app retained for rollback; new installed package awaits runtime verification','exit_status':0}
Path('docs/evidence/seeky6-performance/continuation/install.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result)
