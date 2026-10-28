"""Download the pinned ARM64 RKNN runtime without changing system libraries."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT / 'runtime.lock.json').read_text(encoding='utf-8'))
    for item in lock['files']:
        target = ROOT / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == item['sha256']:
            print('Verified: ' + item['path']);continue
        temporary = target.with_suffix('.part')
        try:
            urllib.request.urlretrieve(item['url'], temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Runtime SHA-256 mismatch; retained previous runtime')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        print('Downloaded and verified: ' + item['path'])


if __name__ == '__main__':
    main()
