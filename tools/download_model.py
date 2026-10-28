"""Download the explicitly pinned public weight, without executing its pickle."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT / 'models.lock.json').read_text(encoding='utf-8'))['selected']
    target = ROOT / 'models/source/visdrone-yolo11n.pt'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == lock['sha256']:
        print('Pinned model already verified:', target)
        return
    request = urllib.request.Request(lock['url'], headers={'User-Agent': 'uav-object-detection/0.1'})
    temporary = target.with_suffix('.download')
    try:
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open('wb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 128 * 1024 * 1024:
                    raise ValueError('Unexpected weight size')
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != lock['sha256']:
            raise ValueError('Model SHA-256 mismatch; existing model was not replaced')
        temporary.replace(target)
        receipt = dict(lock, bytes=size, actualSha256=digest.hexdigest())
        target.with_suffix('.provenance.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'file': str(target), 'bytes': size, 'sha256': digest.hexdigest()}))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
