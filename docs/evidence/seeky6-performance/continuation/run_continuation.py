import json,subprocess,sys,time
from pathlib import Path
root=Path.cwd();out=root/'docs/evidence/seeky6-performance/continuation';runs=[]
probe=root/'.scratch/seeky-proc-memory';script=root/'scripts/verify_seeky_multi.py'
before=Path('/Users/ray/Library/Caches/seeky-native-v6')
assert (before/'pet/frame_edges.py').read_bytes()==(out/'frame_edges_before.py').read_bytes()
for i in range(1,4):
 for label,target in [('before',before),('after',root)]:
  runs.append((f'{label}-{i}',target,100,35,[]))
runs.extend([('after-long',root,620,100,[]),('after-mixed',root,100,35,['--different-actions','--mixed-sizes','--exercise','--churn'])])
results=[]
for label,target,duration,steady,extra in runs:
 command=[sys.executable,str(script),'--root',str(target),'--output',str(out/(label+'.json')),'--probe',str(probe),'--duration',str(duration),'--steady-after',str(steady),'--prewarm','balanced','--scale','1.3','--spawn-api','--expect-warm-limit','2','--expect-shared-first-frames',*extra]
 start=time.monotonic()
 with (out/(label+'.log')).open('w') as log:
  status=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=duration+90).returncode
 data=json.loads((out/(label+'.json')).read_text()) if (out/(label+'.json')).exists() else {}
 record={'label':label,'command':command,'elapsed_seconds':time.monotonic()-start,'exit_status':status,'checks':data.get('checks')}
 results.append(record);(out/'runs.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
 print(label,status,{k:round(v['fps'],3) for k,v in data.get('checks',{}).get('playback',{}).items()},flush=True)
raise SystemExit(int(any(v['exit_status'] for v in results)))
