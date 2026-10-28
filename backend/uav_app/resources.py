"""Real host resources; unavailable NPU/FPS values remain null."""
from pathlib import Path
import platform
import re
import shutil
import socket
import threading

import psutil


def resources(root, cpu_percent=None):
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(root)
    npu = None
    try:
        text = Path('/sys/kernel/debug/rknpu/load').read_text()
        values = {int(core): int(value) for core, value in re.findall(r'Core\s*([012]):\s*(\d+)%', text)}
        if len(values) == 3:
            npu = [values[i] for i in range(3)]
    except OSError:
        pass
    temperatures = []
    for path in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
        try:
            temperatures.append(float(path.read_text()) / 1000)
        except (OSError, ValueError):
            pass
    return {'hostname': socket.gethostname(), 'os': platform.platform(), 'machine': platform.machine(),
            'cpu_percent': cpu_percent, 'logical_cpus': psutil.cpu_count(),
            'memory_percent': memory.percent, 'memory_used': memory.total - memory.available,
            'memory_total': memory.total, 'disk_free': disk.free, 'disk_total': disk.total,
            'npu_percent': npu, 'temperature_c': max(temperatures) if temperatures else None}


class ResourceSampler:
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = None

    def sample(self, root):
        # A shared counter baseline is independent of FastAPI's worker-thread scheduling.
        counters = psutil.cpu_times()._asdict()
        total = sum(value for key, value in counters.items() if key not in ('guest', 'guest_nice', 'interrupt', 'dpc'))
        idle = counters.get('idle', 0) + counters.get('iowait', 0)
        cpu = None
        with self.lock:
            if self.previous:
                delta = total - self.previous[0]
                idle_delta = idle - self.previous[1]
                if delta > 0 and idle_delta >= 0:
                    cpu = max(0, min(100, 100 * (delta - idle_delta) / delta))
            self.previous = total, idle
        return resources(root, cpu)
