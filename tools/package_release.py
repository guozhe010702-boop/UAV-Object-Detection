"""Build independent source, model and board-offline ZIPs; exclude all user data."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def write_zip(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source, name in files:
            archive.write(source, name)
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist()))
    return {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    release = ROOT / 'releases'
    release.mkdir(exist_ok=True)
    source_files = []
    for folder in ('backend', 'conversion', 'frontend/src', 'systemd', 'tools', 'tests'):
        source_files += [(p, p.relative_to(ROOT).as_posix()) for p in (ROOT / folder).rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts]
    for name in ('README.md', 'todo.md', 'VALIDATION.md', 'THIRD_PARTY.md', 'models.lock.json', '.gitignore', '.gitattributes',
                 'frontend/package.json', 'frontend/package-lock.json', 'frontend/vite.config.js',
                 'frontend/index.html', 'frontend/verify-ui.mjs', 'run_windows.ps1'):
        source_files.append((ROOT / name, name))
    artifacts = ROOT / 'artifacts/visdrone-yolo11n-fp16-640'
    bundle = [(p, p.name) for p in artifacts.iterdir() if p.is_file()]
    board_files = [(p, name) for p, name in source_files if name.startswith(('backend/', 'systemd/'))
                   or name in ('README.md', 'VALIDATION.md', 'THIRD_PARTY.md', 'models.lock.json')]
    board_files += [(ROOT / 'tools/bootstrap_venv.py', 'tools/bootstrap_venv.py')]
    board_files += [(p, 'frontend/dist/' + p.relative_to(ROOT / 'frontend/dist').as_posix())
                    for p in (ROOT / 'frontend/dist').rglob('*') if p.is_file()]
    board_files += [(p, 'wheels/' + p.name) for p in (ROOT / '.cache/board-wheels').glob('*.whl')]
    if not any(name.startswith('wheels/') for _, name in board_files):
        raise SystemExit('Prepare ARM64 Python 3.8 offline wheels first')
    board_files += [(p, 'model-bundle/' + name) for p, name in bundle]
    index = {'uav-source.zip': write_zip(release / 'uav-source.zip', source_files),
             'visdrone-yolo11n-rk3588-fp16.zip': write_zip(release / 'visdrone-yolo11n-rk3588-fp16.zip', bundle),
             'uav-web-rk3588-offline.zip': write_zip(release / 'uav-web-rk3588-offline.zip', board_files)}
    (release / 'SHA256.json').write_text(json.dumps(index, indent=2))
    print(json.dumps(index, indent=2))


if __name__ == '__main__':
    main()
