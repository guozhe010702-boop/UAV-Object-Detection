"""One normal reboot to verify the selected camera/model autostarts; no firmware changes."""
import json
from pathlib import Path
import subprocess
import time

from board_probe import ROOT, ADB
from deploy_board import remote


def main():
    before = json.loads(remote('''
import json,urllib.request
from pathlib import Path
root=Path('/userdata/uav-object-detection');token=(root/'data/admin-token.txt').read_text().strip()
def api(path,body=None,method=None):
 req=urllib.request.Request('http://127.0.0.1:8088/api/'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(req,timeout=25))
settings=api('settings');assert settings['active_model'] and settings['source_uri']
api('inference/stop',{},'POST');settings['autostart_inference']=True
api('settings',settings,'PUT')
print(json.dumps({'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'settings':settings}))
'''))
    output = ROOT / '.cache/boot-acceptance.json'
    output.write_text(json.dumps({'before': before, 'result': 'reboot_requested'}, indent=2), encoding='utf-8')
    subprocess.run([str(ADB), 'shell', 'systemctl reboot'], timeout=10, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.monotonic()
    code = '''
import json,urllib.request,subprocess
from pathlib import Path
root=Path('/userdata/uav-object-detection');token=(root/'data/admin-token.txt').read_text().strip()
req=urllib.request.Request('http://127.0.0.1:8088/api/status',headers={'Authorization':'Bearer '+token})
status=json.load(urllib.request.urlopen(req,timeout=3))
print(json.dumps({'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'healthy':status['inference_connected'],'model':status['model']['manifest']['name'],
 'fps':status['processing_fps'],'npu':status.get('npu'),'source':status.get('source'),
 'addresses':subprocess.check_output(['hostname','-I'],text=True).split(),
 'service':subprocess.check_output(['systemctl','is-active','uav-object-detection.service'],text=True).strip()}))
'''
    while time.monotonic() - started < 180:
        time.sleep(2)
        try:
            state = subprocess.run([str(ADB), 'get-state'], capture_output=True, timeout=4)
            if state.stdout.strip() != b'device':continue
            result = json.loads(remote(code, timeout=8))
            if result['boot_id'] != before['boot_id'] and result['healthy']:
                result.update(automaticInference=True, elapsed_seconds=time.monotonic() - started,
                              normalRebootOnly=True, kernelOrFirmwareChanged=False)
                output.write_text(json.dumps({'before': before, 'after': result}, indent=2), encoding='utf-8')
                print(json.dumps(result), flush=True)
                return
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
            pass
    raise RuntimeError('Reboot acceptance did not recover within 180 seconds; inspect board before retrying controls')


if __name__ == '__main__':
    main()
