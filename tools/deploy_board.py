"""First installation only, into a new private directory. No camera or NPU calls."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

from board_probe import ROOT, ADB

DEST = '/userdata/uav-object-detection'


def remote(code, timeout=60):
    command = "python3 -c 'import base64;exec(base64.b64decode(\"" + base64.b64encode(code.encode()).decode() + "\"))'"
    text = subprocess.check_output([str(ADB), 'shell', command], timeout=timeout).decode().replace('\r', '')
    if 'Traceback (most recent call last):' in text:
        raise RuntimeError(text[-4000:])
    return text


def main():
    archive = ROOT / 'releases/uav-web-rk3588-offline.zip'
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(remote("from pathlib import Path;p=Path('" + DEST + "');assert not p.exists(),'Existing install retained; use a reviewed upgrade';p.mkdir()"))
    subprocess.run([str(ADB), 'push', str(archive), DEST + '/install.zip'], check=True, stdout=subprocess.DEVNULL)
    code = """
import hashlib,json,subprocess,os,urllib.request,time
from pathlib import Path
import zipfile
root=Path('/userdata/uav-object-detection');archive=root/'install.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==EXPECTED
with zipfile.ZipFile(archive) as z:
 for item in z.infolist():
  target=(root/item.filename).resolve()
  assert root.resolve() in target.parents,'Invalid package path'
  assert not item.filename.startswith(('data/','.venv/')),'Package contains user state'
 z.extractall(root)
subprocess.run(['python3',str(root/'tools/bootstrap_venv.py')],check=True)
subprocess.run(['bash',str(root/'systemd/install.sh')],check=True)
active=subprocess.check_output(['systemctl','is-active','uav-object-detection.service'],text=True).strip()
enabled=subprocess.check_output(['systemctl','is-enabled','uav-object-detection.service'],text=True).strip()
for attempt in range(30):
 try:
  health=json.load(urllib.request.urlopen('http://127.0.0.1:8088/api/health',timeout=2));break
 except OSError:
  if attempt==29:raise
  time.sleep(.2)
addresses=subprocess.check_output(['hostname','-I'],text=True).split()
report={'service':active,'enabled':enabled,'health':health,'addresses':addresses,'inferenceStarted':False,'cameraOpenedByInstaller':False}
(root/'installation.json').write_text(json.dumps(report,indent=2))
archive.unlink()
print('UAV_INSTALL_RESULT='+json.dumps(report))
""".replace('EXPECTED', repr(digest))
    output = remote(code, timeout=240)
    (ROOT / '.cache/board-install.log').write_text(output, encoding='utf-8')
    print(output[-3000:])


if __name__ == '__main__':
    main()
