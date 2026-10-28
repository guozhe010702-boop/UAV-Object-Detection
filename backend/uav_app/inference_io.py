"""Bounded acquisition, atomic frame publication and UTF-8 annotation."""
from collections import deque
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import io
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont
from .source_auth import authenticated_uri, read_credentials, redact


def atomic_json(path, value):
    temporary = Path(str(path) + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def ffmpeg_environment(binary):
    env = os.environ.copy()
    # The private FFmpeg must not inherit RKNN/RGA libraries from another project.
    env.pop('LD_PRELOAD', None)
    root = Path(binary).resolve().parent.parent
    env['LD_LIBRARY_PATH'] = ':'.join(str(root / x) for x in ('lib', 'lib64'))
    return env


def locate_ffmpeg():
    import shutil
    preferred = '/userdata/av_dev/ffmpeg_pipeline/runtime/bin/ffmpeg'
    binary = os.environ.get('UAV_FFMPEG') or (preferred if Path(preferred).is_file() else shutil.which('ffmpeg'))
    if not binary or not Path(binary).is_file():
        raise ValueError('找不到 FFmpeg，请配置 UAV_FFMPEG')
    return binary


def camera_owners(device):
    owners = []
    for process in Path('/proc').glob('[0-9]*'):
        try:
            if any(str(fd.resolve()) == device for fd in (process / 'fd').iterdir()):
                owners.append({'pid': int(process.name), 'name': (process / 'comm').read_text().strip()})
        except OSError:
            pass
    return owners


def actual_camera_format(device):
    """Read G_FMT only; never change the stream's format or requested frame rate."""
    import shutil
    binary = shutil.which('v4l2-ctl')
    if not binary:
        return None
    try:
        result = subprocess.run([binary, '-d', device, '--get-fmt-video'], capture_output=True, timeout=2)
        text = result.stdout.decode('utf-8', errors='replace')
        dimensions = re.search(r'Width/Height\s*:\s*(\d+)/(\d+)', text)
        fourcc = re.search(r"Pixel Format\s*:\s*'([^']+)'", text)
        planes = re.search(r'Number of planes\s*:\s*(\d+)', text)
        if result.returncode or not dimensions or not fourcc:
            return None
        return {'width': int(dimensions[1]), 'height': int(dimensions[2]), 'fourcc': fourcc[1],
                'planes': int(planes[1]) if planes else 1,
                'strides': [int(x) for x in re.findall(r'Bytes per Line\s*:\s*(\d+)', text)],
                'size_images': [int(x) for x in re.findall(r'Size Image\s*:\s*(\d+)', text)],
                'fps': None, 'scope': 'V4L2 G_FMT; sensor frame interval not inferred from requested FPS'}
    except (OSError, subprocess.SubprocessError):
        return None


def source_spec(store, settings):
    kind, uri = settings.source_kind, settings.source_uri
    if not uri:
        raise ValueError('请先选择视频源或上传素材')
    binary = locate_ffmpeg()
    env = ffmpeg_environment(binary)
    if kind == 'file':
        asset = store.asset(uri)
        if not asset:
            raise ValueError('素材不存在')
        from .store import safe_file
        path = safe_file(store.root / 'uploads', asset['filename'])
        if not path.is_file():
            raise ValueError('素材文件已缺失')
        if asset['kind'] == 'image':
            with Image.open(path) as image:
                width, height = image.size
            return {'kind': 'image', 'uri': str(path), 'name': asset['name'], 'width': width, 'height': height, 'fps': None}
        args = ['-re', '-i', str(path)]
        target = str(path)
        name = asset['name']
    elif kind in ('usb', 'imx415'):
        if kind == 'usb':
            from .cameras import is_usb_node
            if not is_usb_node(uri):
                raise ValueError('该节点未识别为 USB 摄像头，请扫描实际 USB 设备；CSI/ISP 节点不能作为 USB 实测')
        if not Path(uri).exists() or not os.access(uri, os.R_OK | os.W_OK):
            raise ValueError('无法访问相机节点；请检查节点与 video 组权限')
        owners = camera_owners(uri)
        if owners:
            raise ValueError('相机正在被占用：' + json.dumps(owners, ensure_ascii=False) + '。请先通过原程序停止采集，或改用现有 RTSP')
        return {'kind': kind, 'name': uri, 'width': settings.camera_width, 'height': settings.camera_height,
                'fps': settings.camera_fps, 'args': ['-f', 'v4l2', '-input_format', settings.camera_format,
                '-video_size', '%sx%s' % (settings.camera_width, settings.camera_height),
                '-framerate', str(settings.camera_fps), '-i', uri], 'binary': binary,
                'mode_scope': '相机请求模式；实际尺寸以 FFmpeg 采集日志为准'}
    else:
        target = authenticated_uri(store.root, uri)
        args = ['-rtsp_transport', 'tcp', '-timeout', '8000000', '-i', target]
        name = uri
    probe = str(Path(binary).with_name('ffprobe'))
    if not Path(probe).is_file():
        import shutil
        probe = shutil.which('ffprobe')
    if not probe:
        raise ValueError('找不到 ffprobe，无法核对视频尺寸')
    command = [probe, '-v', 'error']
    if kind == 'rtsp':
        command += ['-rtsp_transport', 'tcp', '-timeout', '8000000']
    command += ['-select_streams', 'v:0', '-show_entries', 'stream=width,height,avg_frame_rate', '-of', 'json', target]
    try:
        result = subprocess.run(command, env=env, capture_output=True, timeout=12, check=True)
        stream = json.loads(result.stdout)['streams'][0]
        width, height = int(stream['width']), int(stream['height'])
        numerator, denominator = stream.get('avg_frame_rate', '0/1').split('/')
        fps = float(numerator) / float(denominator) if float(denominator) else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as error:
        raise ValueError('无法读取视频源，请检查文件、网络和视频格式') from error
    if not 0 < width * height <= 40_000_000:
        raise ValueError('视频尺寸无效或超过上限')
    return {'kind': kind, 'name': name, 'width': width, 'height': height, 'fps': fps,
            'args': args, 'binary': binary, 'mode_scope': 'ffprobe 报告的视频尺寸与声明帧率'}


class LatestFrames:
    """One waiting frame. Completing inference never holds a V4L2/decoder buffer."""
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = deque(maxlen=1)
        self.received = self.dropped = 0
        self.closed = False
        self.error = None

    def put(self, image):
        with self.condition:
            self.received += 1
            if self.pending:
                self.dropped += 1
            self.pending.append((self.received, time.monotonic(), image))
            self.condition.notify_all()

    def finish(self, error=None):
        with self.condition:
            self.error, self.closed = error, True
            self.condition.notify_all()

    def take(self, timeout=12):
        with self.condition:
            if not self.pending and not self.closed:
                self.condition.wait_for(lambda: self.pending or self.closed, timeout=timeout)
            if self.pending:
                return self.pending.popleft()
            if self.error:
                raise RuntimeError(self.error)
            if not self.closed:
                raise RuntimeError('视频源超过 12 秒未出帧')
            return None


def read_exact(stream, count):
    data = bytearray()
    while len(data) < count:
        block = stream.read(count - len(data))
        if not block:
            if data:
                raise RuntimeError('FFmpeg 返回不完整原始帧')
            return None
        data.extend(block)
    return bytes(data)


class Capture:
    def __init__(self, spec, preview_width, log, credentials=None):
        self.frames = LatestFrames()
        self.process = None
        self.spec = spec
        self.log_thread = None
        self.credentials = credentials
        width = min(preview_width, spec['width'])
        height = max(2, round(spec['height'] * width / spec['width'] / 2) * 2)
        self.size = (width, height)
        if spec['kind'] == 'image':
            with Image.open(spec['uri']) as image:
                self.frames.put(image.convert('RGB').resize(self.size, Image.Resampling.BILINEAR))
            self.frames.finish()
            self.thread = None
            return
        command = [spec['binary'], '-hide_banner', '-nostdin', '-loglevel', 'info', '-threads', '2'] + spec['args']
        command += ['-map', '0:v:0', '-an', '-vf', 'scale=%s:%s' % self.size,
                    '-threads', '2', '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                        env=ffmpeg_environment(spec['binary']))
        def pump_log():
            while True:
                line = self.process.stderr.readline(8192)
                if not line:break
                log.write(redact(line.decode('utf-8', errors='replace'), credentials).encode('utf-8'))
        self.log_thread = threading.Thread(target=pump_log, name='uav-capture-log', daemon=True)
        self.log_thread.start()
        self.thread = threading.Thread(target=self.read, name='uav-capture', daemon=True)
        self.thread.start()

    def read(self):
        try:
            while True:
                raw = read_exact(self.process.stdout, self.size[0] * self.size[1] * 3)
                if raw is None:
                    code = self.process.wait(timeout=3)
                    error = 'FFmpeg 采集退出 (%s)，查看采集日志' % code if code else None
                    if not code and self.spec['kind'] != 'file':
                        error = '实时视频源已断开；请检查相机或 RTSP，再重新启动检测'
                    self.frames.finish(error)
                    return
                self.frames.put(Image.frombytes('RGB', self.size, raw))
        except Exception as error:
            self.frames.finish(str(error))

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=2)
            self.process.stdout.close()
        if self.thread:
            self.thread.join(timeout=2)
        if self.log_thread:
            self.log_thread.join(timeout=2)
            self.process.stderr.close()


def annotation(image, detections, labels, classes):
    draw = ImageDraw.Draw(image)
    font_path = os.environ.get('UAV_FONT', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc')
    try:
        font = get_font(font_path, max(14, round(image.width / 70)))
        chinese = True
    except OSError:
        font, chinese = ImageFont.load_default(), False
    palette = ['#5de69e', '#ffd166', '#62c7ff', '#ff9f87', '#c4a0ff']
    for item in detections:
        cid = item['class_id']
        x1, y1, x2, y2 = item['box']
        color = palette[cid % len(palette)]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=max(2, image.width // 600))
        text = '%s %.2f' % ((labels if chinese else classes)[cid], item['confidence'])
        tile = label_tile(text, font, color)
        tx = max(0, min(int(x1), image.width - tile.width)); ty = max(0, int(y1) - tile.height - 2)
        image.paste(tile, (tx, ty))
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=82)
    return output.getvalue()


@lru_cache(maxsize=8)
def get_font(path, size):
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=512)
def label_tile(text, font, color):
    # Chinese glyph rasterization is expensive in dense aerial scenes. The
    # immutable label tile includes the rounded confidence; boxes still use the
    # exact current frame's detections. Bounded cache prevents memory growth.
    box = font.getbbox(text)
    tile = Image.new('RGB', (box[2] - box[0] + 6, box[3] - box[1] + 6), color)
    ImageDraw.Draw(tile).text((3 - box[0], 3 - box[1]), text, font=font, fill='#14271f')
    return tile
