from typing import List, Literal, Optional
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    architecture: Literal['yolo11n'] = 'yolo11n'
    platform: Literal['rk3588'] = 'rk3588'
    input_size: List[int]
    classes: List[str] = Field(min_length=1, max_length=256)
    labels_zh: Optional[List[str]] = None
    output_layout: Literal['rockchip-yolo11-dfl-9']
    precision: Literal['fp16', 'int8']
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    onnx_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source: str = Field(max_length=500)
    license: str = Field(max_length=300)
    exported_at: str = Field(max_length=100)
    validated_on_board: Literal[False] = False
    outputs: List[dict]
    preprocessing: dict
    conversion: dict

    @model_validator(mode='after')
    def contract(self):
        if self.input_size != [640, 640]:
            raise ValueError('本版部署契约仅支持 640×640 输入')
        if len(set(self.classes)) != len(self.classes) or any(not s.strip() or len(s) > 80 for s in self.classes):
            raise ValueError('类别必须非空、唯一且不超过 80 字符')
        if self.labels_zh is not None and len(self.labels_zh) != len(self.classes):
            raise ValueError('中文名称必须与类别逐项对应')
        if len(self.outputs) != 9:
            raise ValueError('RK 优化模型必须有 9 个输出')
        for i, grid in enumerate((80, 40, 20)):
            expected = [[1, 64, grid, grid], [1, len(self.classes), grid, grid], [1, 1, grid, grid]]
            if [x.get('shape') for x in self.outputs[i * 3:i * 3 + 3]] != expected:
                raise ValueError('检测头形状与输入或类别数量不一致')
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confidence: float = Field(default=0.25, ge=0.01, le=0.99)
    iou: float = Field(default=0.45, ge=0.01, le=0.99)
    source_kind: Literal['file', 'rtsp', 'usb', 'imx415'] = 'file'
    source_uri: str = Field(default='', max_length=500)
    active_model: Optional[str] = None
    record_interval: int = Field(default=1, ge=1, le=3600)
    preview_width: int = Field(default=1280, ge=320, le=1920)
    autostart_inference: bool = False
    camera_width: int = Field(default=1920, ge=320, le=3840)
    camera_height: int = Field(default=1080, ge=240, le=2160)
    camera_fps: int = Field(default=30, ge=1, le=60)
    camera_format: Literal['nv12', 'yuyv422', 'mjpeg'] = 'nv12'

    @field_validator('active_model')
    @classmethod
    def identifier(cls, value):
        if value is not None:
            import re
            if not re.fullmatch(r'[a-f0-9]{32}', value):
                raise ValueError('模型标识无效')
        return value

    @model_validator(mode='after')
    def source(self):
        import re
        if self.camera_width % 2 or self.camera_height % 2:
            raise ValueError('相机宽高必须为偶数')
        if not self.source_uri:
            return self
        if self.source_kind == 'rtsp':
            parsed = urlsplit(self.source_uri)
            if parsed.scheme not in ('rtsp', 'rtsps') or not parsed.hostname:
                raise ValueError('请输入有效 RTSP 地址')
            if parsed.username or parsed.password:
                raise ValueError('请在独立认证栏输入用户名与密码，不要写入 RTSP 地址')
        elif self.source_kind in ('usb', 'imx415'):
            if not re.fullmatch(r'/dev/video[0-9]+', self.source_uri):
                raise ValueError('摄像头节点应为 /dev/video数字')
        elif not re.fullmatch(r'[a-f0-9]{32}', self.source_uri):
            raise ValueError('请选择已上传的媒体文件')
        return self
