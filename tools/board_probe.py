"""Read-only ADB capability report; never opens a camera or initializes RKNN."""
import base64
import json
from pathlib import Path
import subprocess
import os
import shutil

ROOT = Path(__file__).resolve().parents[1]
ADB = Path(os.environ.get('UAV_ADB') or shutil.which('adb') or str(
    ROOT.parents[1] / 'Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe'))
CODE = """
import json,sys,platform,shutil,subprocess
from pathlib import Path
owners=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  if any(str(x.resolve())=='/dev/video44' for x in (p/'fd').iterdir()):
   owners.append({'pid':int(p.name),'name':(p/'comm').read_text().strip()})
 except OSError:pass
print(json.dumps({'python':sys.version.split()[0],'machine':platform.machine(),
 'osRelease':Path('/etc/os-release').read_text(),'freeBytes':shutil.disk_usage('/userdata').free,
 'existingWebDirectory':Path('/userdata/uav-object-detection').exists(),'cameraOwners':owners}))
"""


def main():
    command = "python3 -c 'import base64;exec(base64.b64decode(\"" + base64.b64encode(CODE.encode()).decode() + "\"))'"
    output = subprocess.check_output([str(ADB), 'shell', command], timeout=30).decode().replace('\r', '')
    report = json.loads(output)
    folder = ROOT / '.cache'
    folder.mkdir(exist_ok=True)
    (folder / 'board-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
