"""Upgrade only this service's code/environment; back up code, retain user data."""
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

from board_probe import ROOT, ADB
from deploy_board import remote, DEST


def main():
    library = ROOT / 'runtime/lib/librknnrt.so'
    if not library.is_file():
        raise SystemExit('Prepare the verified private RKNN runtime under runtime/lib first')
    package = ROOT / '.cache/step02-upgrade.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
        for folder in ('backend', 'systemd', 'frontend/dist', 'runtime'):
            for file in (ROOT / folder).rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts:
                    archive.write(file, file.relative_to(ROOT).as_posix())
        for name in ('README.md', 'VALIDATION.md', 'THIRD_PARTY.md', 'todo.md', 'runtime.lock.json', 'models.lock.json',
                     'tools/prepare_runtime.py', 'tools/validate_npu.py'):
            archive.write(ROOT / name, name)
        for file in (ROOT / '.cache/board-wheels').glob('numpy-*.whl'):
            archive.write(file, 'wheels/' + file.name)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    version_text = (ROOT / 'backend/uav_app/__init__.py').read_text(encoding='utf-8')
    version = re.search(r"__version__\s*=\s*'([^']+)'", version_text).group(1)
    subprocess.run([str(ADB), 'push', str(package), DEST + '/step02-upgrade.zip'], check=True, stdout=subprocess.DEVNULL)
    code = '''
import hashlib,json,subprocess,zipfile,time,tarfile,urllib.request
from pathlib import Path
root=Path('/userdata/uav-object-detection');package=root/'step02-upgrade.zip'
assert hashlib.sha256(package.read_bytes()).hexdigest()==EXPECTED
unit=Path('/etc/systemd/system/uav-object-detection.service')
old_unit=unit.read_bytes()
old_metrics=Path('/etc/systemd/system/uav-npu-metrics.service')
metrics_bytes=old_metrics.read_bytes() if old_metrics.exists() else None
backup=root/('backup-code-'+time.strftime('%Y%m%d-%H%M%S')+'.tar.gz')
with tarfile.open(backup,'w:gz') as tar:
 for name in ('backend','frontend/dist','systemd','README.md','VALIDATION.md','THIRD_PARTY.md','todo.md','runtime.lock.json','models.lock.json'):
  if (root/name).exists():tar.add(root/name,arcname=name)
try:
 subprocess.run(['systemctl','stop','uav-object-detection.service'],check=True)
 with zipfile.ZipFile(package) as z:
  for item in z.infolist():
   assert root in (root/item.filename).resolve().parents
   assert item.filename.startswith(('backend/','frontend/dist/','systemd/','runtime/','wheels/')) or item.filename in ('README.md','VALIDATION.md','THIRD_PARTY.md','todo.md','runtime.lock.json','models.lock.json','tools/prepare_runtime.py','tools/validate_npu.py')
  z.extractall(root)
 subprocess.run([str(root/'.venv/bin/python'),'-m','pip','install','--no-index','--find-links',str(root/'wheels'),'-r',str(root/'backend/requirements.txt')],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(['bash',str(root/'systemd/install.sh'),'--upgrade'],check=True)
 for attempt in range(50):
  try:
   health=json.load(urllib.request.urlopen('http://127.0.0.1:8088/api/health',timeout=2))
   if health.get('version')==EXPECTED_VERSION:break
  except OSError:pass
  time.sleep(.2)
 else:raise RuntimeError('Upgraded service did not become healthy')
except BaseException:
 subprocess.run(['systemctl','stop','uav-object-detection.service'],check=False)
 with tarfile.open(backup) as tar:tar.extractall(root)
 unit.write_bytes(old_unit)
 if metrics_bytes is not None:old_metrics.write_bytes(metrics_bytes)
 else:
  subprocess.run(['systemctl','disable','--now','uav-npu-metrics.service'],check=False)
  old_metrics.unlink(missing_ok=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','start','uav-object-detection.service'],check=True)
 raise
package.unlink()
print(json.dumps({'backup':str(backup),'service':subprocess.check_output(['systemctl','is-active','uav-object-detection.service'],text=True).strip()}))
'''.replace('EXPECTED_VERSION', repr(version)).replace('EXPECTED', repr(digest))
    print(remote(code, timeout=180).encode('ascii', errors='backslashreplace').decode())


if __name__ == '__main__':
    main()
