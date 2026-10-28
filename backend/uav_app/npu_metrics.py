"""Read only one fixed debugfs counter; publish non-sensitive load for the web user.

The tiny system service is privileged only to read debugfs. The web/NPU process
still runs as uav-web, never root. No commands, network, paths or input are accepted.
"""
import json
from pathlib import Path
import re
import time


def main():
    folder = Path('/run/uav-object-detection')
    while True:
        value = None
        try:
            raw = Path('/sys/kernel/debug/rknpu/load').read_text()
            cores = {int(i): int(v) for i, v in re.findall(r'Core\s*([012]):\s*(\d+)%', raw)}
            if len(cores) == 3:
                value = [cores[i] for i in range(3)]
        except OSError:
            pass
        temporary = folder / 'npu.tmp'
        temporary.write_text(json.dumps({'at': time.time(), 'percent': value}), encoding='utf-8')
        temporary.chmod(0o644)
        temporary.replace(folder / 'npu.json')
        time.sleep(1)


if __name__ == '__main__':
    main()
