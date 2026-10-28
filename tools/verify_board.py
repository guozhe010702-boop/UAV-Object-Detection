"""Read-back existing web deployment; never starts inference or reveals its access code."""
import json
from pathlib import Path
from deploy_board import ROOT, remote
import hashlib


def main():
    source = ROOT / 'backend/uav_app/app.py'
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    code = """
import json,hashlib,urllib.request,subprocess,time,http.cookiejar
from pathlib import Path
root=Path('/userdata/uav-object-detection')
assert hashlib.sha256((root/'backend/uav_app/app.py').read_bytes()).hexdigest()==EXPECTED
for i in range(30):
 try:
  health=json.load(urllib.request.urlopen('http://127.0.0.1:8088/api/health',timeout=2));break
 except OSError:
  if i==29:raise
  time.sleep(.2)
token=(root/'data/admin-token.txt').read_text().strip()
def get(path):
 request=urllib.request.Request('http://127.0.0.1:8088/api/'+path,headers={'Authorization':'Bearer '+token})
 return json.load(urllib.request.urlopen(request,timeout=10))
status=get('status');models=get('models');records=get('records');statistics=get('statistics')
assert models and len(models[0]['manifest']['classes'])==11
assert records['total']==statistics['samples']
if status['state']=='running':
 assert status['npu']['core_mask']==7 and status['inference_connected']
owners=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  if any(str(x.resolve())=='/dev/video44' for x in (p/'fd').iterdir()):owners.append(int(p.name))
 except OSError:pass
unit=subprocess.check_output(['systemctl','show','uav-object-detection.service','--property=User,ActiveState,UnitFileState'],text=True)
report={'health':health,'statusPhase':status['phase'],'modelCount':len(models),'classes':len(models[0]['manifest']['classes']),
 'records':records['total'],'serviceProperties':unit,'cameraOwners':owners,
 'npuInferencePerformed':any(m['status']=='npu_execution_verified' for m in models),
 'processingFps':status['processing_fps'],'npuPercent':status['resources']['npu_percent'],
 'appSha256':EXPECTED,'cpu':status['resources']['cpu_percent'],'memoryPercent':status['resources']['memory_percent']}
print(json.dumps(report))
""".replace('EXPECTED', repr(expected))
    report = json.loads(remote(code, timeout=40))
    (ROOT / '.cache/board-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
