"""Install build-only Node in this project's cache; verify official SHA-256."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'v22.16.0'
NAME = 'node-' + VERSION + '-win-x64'


def main():
    cache = ROOT / '.cache'
    cache.mkdir(exist_ok=True)
    if (cache / NAME / 'node.exe').exists():
        print(cache / NAME)
        return
    base = 'https://nodejs.org/dist/' + VERSION + '/'
    checksums = urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=60).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.endswith(NAME + '.zip'))
    payload = urllib.request.urlopen(base + NAME + '.zip', timeout=120).read()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError('Node checksum mismatch')
    archive = cache / (NAME + '.zip')
    archive.write_bytes(payload)
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            target = (cache / entry.filename).resolve()
            if cache.resolve() not in target.parents:
                raise ValueError('Unexpected archive path')
        source.extractall(cache)
    (cache / 'node-sha256.txt').write_text(expected + '  ' + NAME + '.zip\n')
    print(cache / NAME)


if __name__ == '__main__':
    main()
