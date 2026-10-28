"""Serialized lifecycle supervisor. Native RKNN never runs in the HTTP process."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .inference_io import source_spec, atomic_json
from .store import safe_file


class Engine:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.process = None
        self.folder = None
        self.running_settings = None
        self.last_state = None

    def _state(self):
        value = {'state': 'idle', 'processing_fps': None, 'inference_ms': None, 'current_counts': None,
                 'frame_id': None, 'error': None, 'frames_processed': 0}
        if self.folder:
            try:
                value.update(json.loads((self.folder / 'status.json').read_text(encoding='utf-8')))
            except (OSError, ValueError):
                value['state'] = 'starting'
            if self.process and self.process.poll() is not None and value['state'] not in ('completed', 'stopped', 'error'):
                value.update(state='error', error='推理进程意外退出 (%s)，请查看检测日志' % self.process.returncode)
        elif self.last_state:
            value.update(self.last_state)
        return value

    def status(self):
        with self.lock:
            value = self._state()
            now = time.time()
            age = now - value['preview_updated_at'] if value.get('preview_updated_at') else None
            value['frame_age_seconds'] = age
            value['stale'] = value['state'] == 'running' and (age is None or age > 5)
            if value['stale']:
                value['processing_fps'] = 0
                value['current_counts'] = None
            if value['state'] in ('error', 'idle', 'stopped', 'starting'):
                value['current_counts'] = None
                value['processing_fps'] = None
            value['inference_connected'] = value['state'] == 'running' and not value['stale']
            value['running_settings'] = self.running_settings
            value['worker_pid'] = self.process.pid if self.process and self.process.poll() is None else None
            return value

    def start(self, settings=None):
        with self.lock:
            if self.process and self.process.poll() is None:
                return self.status()
            settings = settings or self.store.settings()
            if not settings.active_model:
                raise ValueError('请先在模型管理中选择 RKNN 模型')
            entry = self.store.model(settings.active_model)
            if not entry:
                raise ValueError('所选模型不存在')
            spec = source_spec(self.store, settings)
            library = Path(os.environ.get('UAV_RKNN_LIBRARY', str(Path(__file__).resolve().parents[2] / 'runtime/lib/librknnrt.so')))
            if not library.is_file():
                raise ValueError('缺少项目私有 RKNN 运行库，请先部署 NPU 运行包')
            # Keep changing frames/status off eMMC. Both web and worker use the same private directory.
            ram = Path('/dev/shm')
            parent = str(ram) if os.name != 'nt' and ram.is_dir() and os.access(str(ram), os.W_OK) else None
            folder = Path(tempfile.mkdtemp(prefix='uav-inference-', dir=parent))
            if self.folder:
                self._archive_and_clean()
            self.folder = folder
            config = {'run_dir': str(folder), 'data_dir': str(self.store.root), 'model_id': entry['id'],
                      'model_path': str(safe_file(self.store.root / 'models', entry['id'] + '.rknn')),
                      'manifest': entry['manifest'], 'source': spec, 'settings': settings.model_dump(), 'library': str(library)}
            atomic_json(folder / 'config.json', config)
            atomic_json(folder / 'status.json', {'state': 'starting', 'updated_at': time.time()})
            env = os.environ.copy()
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
            env['OPENBLAS_NUM_THREADS'] = '1'
            env['OMP_NUM_THREADS'] = '1'
            env['LD_LIBRARY_PATH'] = str(library.parent)
            try:
                with (folder / 'worker.log').open('wb') as log:
                    self.process = subprocess.Popen([sys.executable, '-u', '-m', 'uav_app.worker', str(folder / 'config.json')],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, start_new_session=os.name != 'nt')
                self.running_settings = settings.model_dump()
                self.last_state = None
            except BaseException:
                self._archive_and_clean()
                raise
            return self.status()

    def stop(self):
        with self.lock:
            if self.process:
                # Signal the owned process group, including its own FFmpeg, never another app.
                if os.name != 'nt':
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                elif self.process.poll() is None:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                    self.process.wait(timeout=3)
            value = self._state()
            value.update(state='stopped', processing_fps=None, current_counts=None, frame_id=None, error=None)
            self.last_state = value
            self._archive_and_clean()
            self.process = None
            self.running_settings = None
            return self.status()

    def _archive_and_clean(self):
        if not self.folder:
            return
        logs = self.store.root / 'logs'
        logs.mkdir(exist_ok=True)
        for name in ('worker.log', 'capture.log'):
            path = self.folder / name
            if path.is_file():
                # Only the latest run is retained, bounded to 256 KiB per log.
                with path.open('rb') as source:
                    source.seek(max(0, path.stat().st_size - 256 * 1024))
                    (logs / name).write_bytes(source.read())
        shutil.rmtree(self.folder)
        self.folder = None

    def logs(self):
        with self.lock:
            folder = self.folder or self.store.root / 'logs'
            result = {}
            for name in ('worker.log', 'capture.log'):
                try:
                    with (folder / name).open('rb') as source:
                        source.seek(max(0, (folder / name).stat().st_size - 16000))
                        result[name] = source.read().decode('utf-8', errors='replace')
                except OSError:
                    result[name] = ''
            return result

    def frame(self):
        with self.lock:
            if not self.folder:
                return None
            try:
                return (self.folder / 'frame.jpg').read_bytes()
            except OSError:
                return None
