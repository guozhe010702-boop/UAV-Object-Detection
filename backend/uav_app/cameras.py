"""Read-only device discovery. CSI/ISP nodes must never count as USB acceptance."""
from pathlib import Path
import shutil
import subprocess


def list_cameras():
    values = []
    binary = shutil.which('v4l2-ctl')
    for node in sorted(Path('/sys/class/video4linux').glob('video*')):
        try:
            device_path = str((node / 'device').resolve())
            usb = '/usb' in device_path
            if not usb and node.name != 'video44':continue
            value = {'device': '/dev/' + node.name, 'name': (node / 'name').read_text().strip(),
                     'kind': 'usb' if usb else 'imx415', 'formats': None}
            if binary and usb:
                result = subprocess.run([binary, '-d', value['device'], '--list-formats-ext'],
                                        capture_output=True, timeout=2)
                value['formats'] = result.stdout.decode('utf-8', errors='replace')[:12000]
            values.append(value)
        except (OSError, subprocess.SubprocessError):
            pass
    return values


def is_usb_node(device):
    path = Path('/sys/class/video4linux') / Path(device).name / 'device'
    return path.exists() and '/usb' in str(path.resolve())
