"""Build independent source, model and board-offline ZIPs; exclude all user data."""
import hashlib
import json
from pathlib import Path
import zipfile
import argparse

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--precision', choices=('fp16', 'int8'), default='int8',
                        help='default board bundle; use fp16 explicitly for an FP16-only build')
    args = parser.parse_args()
    release = ROOT / 'releases'
    release.mkdir(exist_ok=True)
    source_files = []
    for folder in ('backend', 'conversion', 'frontend/src', 'systemd', 'tools', 'tests'):
        source_files += [(p, p.relative_to(ROOT).as_posix()) for p in (ROOT / folder).rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts]
    for name in ('README.md', 'todo.md', 'VALIDATION.md', 'THIRD_PARTY.md', 'models.lock.json', 'runtime.lock.json', '.gitignore', '.gitattributes',
                 'frontend/package.json', 'frontend/package-lock.json', 'frontend/vite.config.js',
                 'frontend/index.html', 'frontend/verify-ui.mjs', 'frontend/verify-live.mjs', 'frontend/verify-stability.mjs', 'run_windows.ps1'):
        source_files.append((ROOT / name, name))
    # Only small aggregate reports are published, never raw predictions/media/credentials.
    for filename in ('visdrone-fp16-metrics.json', 'visdrone-int8-metrics.json', 'real-camera-30min.json',
                     'browser-30min.json', 'acceptance.json', '验收与性能.md'):
        file = ROOT / 'reports' / filename
        if file.is_file():source_files.append((file, 'reports/' + filename))
    artifacts = ROOT / ('artifacts/visdrone-yolo11n-' + args.precision + '-640')
    if not artifacts.is_dir():raise SystemExit('Build the selected model before packaging: ' + args.precision)
    bundle = [(p, p.name) for p in artifacts.iterdir() if p.is_file()]
    board_files = [(p, name) for p, name in source_files if name.startswith(('backend/', 'systemd/'))
                   or name in ('README.md', 'VALIDATION.md', 'THIRD_PARTY.md', 'models.lock.json', 'runtime.lock.json')]
    board_files += [(ROOT / ('tools/' + name), 'tools/' + name)
                    for name in ('bootstrap_venv.py', 'validate_npu.py', 'prepare_runtime.py', 'monitor_stability.py', 'evaluate_board.py')]
    runtime = ROOT / 'runtime/lib/librknnrt.so'
    lock = json.loads((ROOT / 'runtime.lock.json').read_text(encoding='utf-8'))
    if not runtime.is_file() or hashlib.sha256(runtime.read_bytes()).hexdigest() != lock['files'][0]['sha256']:
        raise SystemExit('Prepare the pinned private runtime first')
    board_files += [(runtime, 'runtime/lib/librknnrt.so')]
    board_files += [(p, 'frontend/dist/' + p.relative_to(ROOT / 'frontend/dist').as_posix())
                    for p in (ROOT / 'frontend/dist').rglob('*') if p.is_file()]
    board_files += [(p, 'wheels/' + p.name) for p in (ROOT / '.cache/board-wheels').glob('*.whl')]
    if not any(name.startswith('wheels/') for _, name in board_files):
        raise SystemExit('Prepare ARM64 Python 3.8 offline wheels first')
    board_files += [(p, 'model-bundle/' + name) for p, name in bundle if name != 'model.onnx']
    fallback = ROOT / 'artifacts/visdrone-yolo11n-fp16-640'
    if args.precision == 'int8' and fallback.is_dir():
        board_files += [(p, 'model-fallback/' + p.name) for p in fallback.iterdir()
                        if p.is_file() and p.name != 'model.onnx']
    index = {'uav-source.zip': write_zip(release / 'uav-source.zip', source_files),
             'visdrone-yolo11n-rk3588-' + args.precision + '.zip': write_zip(release / ('visdrone-yolo11n-rk3588-' + args.precision + '.zip'), bundle),
             'uav-web-rk3588-offline.zip': write_zip(release / 'uav-web-rk3588-offline.zip', board_files)}
    (release / 'SHA256.json').write_text(json.dumps(index, indent=2))
    print(json.dumps(index, indent=2))


if __name__ == '__main__':
    main()
