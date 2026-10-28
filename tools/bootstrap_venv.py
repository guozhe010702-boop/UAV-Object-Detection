"""Create a board-private environment from locally supplied pure-Python wheels."""
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 8):
        raise SystemExit('Python 3.8 or newer is required')
    environment = ROOT / '.venv'
    interpreter = environment / 'bin/python'
    if not interpreter.exists():
        bootstrap = ROOT / '.cache/bootstrap'
        bootstrap.mkdir(parents=True, exist_ok=True)
        for distribution in ('virtualenv', 'distlib', 'filelock', 'platformdirs'):
            matches = sorted((ROOT / 'wheels').glob(distribution + '-*.whl'))
            if len(matches) != 1:
                raise SystemExit('Exactly one offline wheel required: ' + distribution)
            with zipfile.ZipFile(matches[0]) as archive:
                for entry in archive.infolist():
                    destination = (bootstrap / entry.filename).resolve()
                    if bootstrap.resolve() not in destination.parents:
                        raise ValueError('Invalid wheel entry')
                archive.extractall(bootstrap)
        sys.path.insert(0, str(bootstrap))
        from virtualenv import cli_run
        cli_run([str(environment), '--no-download', '--no-periodic-update', '--app-data', str(ROOT / '.cache/virtualenv')])
    subprocess.run([str(interpreter), '-m', 'pip', 'install', '--no-index', '--find-links', str(ROOT / 'wheels'),
                    '-r', str(ROOT / 'backend/requirements.txt')], check=True)


if __name__ == '__main__':
    main()
