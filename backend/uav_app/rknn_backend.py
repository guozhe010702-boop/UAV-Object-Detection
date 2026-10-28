"""Small, synchronous ctypes binding to the pinned RKNN 2.3.2 C ABI (ARM64).

Only the worker imports this module. No CPU inference fallback is provided.
See THIRD_PARTY.md for the official API source. No SDK headers are vendored.
"""
import ctypes as C
import hashlib
import platform
from pathlib import Path
import numpy as np

U32, I32 = C.c_uint32, C.c_int32


class Attr(C.Structure):
    _fields_ = [('index', U32), ('n_dims', U32), ('dims', U32 * 16), ('name', C.c_char * 256),
                ('n_elems', U32), ('size', U32), ('fmt', I32), ('type', I32), ('qnt_type', I32),
                ('fl', C.c_int8), ('zp', I32), ('scale', C.c_float), ('w_stride', U32),
                ('size_with_stride', U32), ('pass_through', C.c_uint8), ('h_stride', U32)]


class Input(C.Structure):
    _fields_ = [('index', U32), ('buf', C.c_void_p), ('size', U32), ('pass_through', C.c_uint8),
                ('type', I32), ('fmt', I32)]


class Output(C.Structure):
    _fields_ = [('want_float', C.c_uint8), ('is_prealloc', C.c_uint8), ('index', U32),
                ('buf', C.c_void_p), ('size', U32)]


class Count(C.Structure):
    _fields_ = [('n_input', U32), ('n_output', U32)]


class Version(C.Structure):
    _fields_ = [('api', C.c_char * 256), ('driver', C.c_char * 256)]


def checked(value, operation):
    if value != 0:
        raise RuntimeError('%s 失败 (RKNN=%s)，未切换 CPU；检查模型、运行库和驱动兼容性' % (operation, value))


class RKNN:
    def __init__(self, model, manifest, library):
        self.context = C.c_uint64(0)
        if platform.machine().lower() not in ('aarch64', 'arm64') or platform.system() != 'Linux':
            raise RuntimeError('NPU 推理仅支持 RK3588 Linux ARM64 板端')
        raw = Path(model).read_bytes()
        pre = manifest.get('preprocessing', {})
        expected = {'color': 'RGB', 'layout': 'NHWC', 'host_dtype': 'uint8', 'letterbox': True,
                    'pad_value': 0, 'mean': [0, 0, 0], 'std': [255, 255, 255]}
        if any(pre.get(k) != v for k, v in expected.items()):
            raise RuntimeError('模型预处理契约不匹配；需 RGB uint8、黑色 letterbox、模型内除以 255')
        if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
            raise RuntimeError('模型摘要与清单不一致')
        if not Path(library).is_file():
            raise RuntimeError('缺少项目私有 librknnrt.so，请安装 NPU 运行包')
        self.lib = C.CDLL(str(library))
        signatures = {
            'rknn_init': [C.POINTER(C.c_uint64), C.c_void_p, U32, U32, C.c_void_p],
            'rknn_query': [C.c_uint64, I32, C.c_void_p, U32],
            'rknn_set_core_mask': [C.c_uint64, I32],
            'rknn_inputs_set': [C.c_uint64, U32, C.POINTER(Input)],
            'rknn_run': [C.c_uint64, C.c_void_p],
            'rknn_outputs_get': [C.c_uint64, U32, C.POINTER(Output), C.c_void_p],
            'rknn_outputs_release': [C.c_uint64, U32, C.POINTER(Output)],
            'rknn_destroy': [C.c_uint64]}
        for name, args in signatures.items():
            getattr(self.lib, name).argtypes = args
            getattr(self.lib, name).restype = I32
        buf = C.create_string_buffer(raw)
        try:
            checked(self.lib.rknn_init(C.byref(self.context), buf, len(raw), 0, None), '初始化模型')
            checked(self.lib.rknn_set_core_mask(self.context, 7), '绑定 NPU CORE_0_1_2')
            count = self.query(0, Count())
            if (count.n_input, count.n_output) != (1, 9):
                raise RuntimeError('只支持单图像输入、九输出 YOLO11 模型')
            self.input = self.query(1, Attr(index=0))
            dims = list(self.input.dims[:self.input.n_dims])
            if dims not in ([1, 3, 640, 640], [1, 640, 640, 3]):
                raise RuntimeError('模型实际输入不是 640×640 RGB')
            self.attrs = [self.query(2, Attr(index=i)) for i in range(9)]
            for attr, expected in zip(self.attrs, manifest['outputs']):
                if list(attr.dims[:attr.n_dims]) != expected['shape'] or attr.fmt != 0:
                    raise RuntimeError('模型输出布局与清单不一致，需要 NCHW 九输出')
            version = self.query(5, Version())
            self.info = {'backend': 'RKNN NPU', 'core_mask': 7, 'cores': [0, 1, 2],
                         'runtime': version.api.decode(errors='replace'), 'driver': version.driver.decode(errors='replace'),
                         'input_shape': dims, 'contexts': 1}
        except BaseException:
            self.close()
            raise

    def query(self, command, value):
        checked(self.lib.rknn_query(self.context, command, C.byref(value), C.sizeof(value)), '查询模型属性')
        return value

    def infer(self, rgb):
        array = np.ascontiguousarray(rgb, dtype=np.uint8)
        if array.shape != (640, 640, 3):
            raise ValueError('RGB 输入尺寸无效')
        source = Input(index=0, buf=array.ctypes.data, size=array.nbytes, pass_through=0, type=3, fmt=1)
        checked(self.lib.rknn_inputs_set(self.context, 1, C.byref(source)), '设置 RGB 输入')
        checked(self.lib.rknn_run(self.context, None), 'NPU 推理')
        outputs = (Output * 9)(*(Output(want_float=1, index=i) for i in range(9)))
        checked(self.lib.rknn_outputs_get(self.context, 9, outputs, None), '读取输出')
        try:
            result = []
            for value, attr in zip(outputs, self.attrs):
                if not value.buf or value.size < attr.n_elems * 4:
                    raise RuntimeError('RKNN 输出长度无效')
                array = np.ctypeslib.as_array(C.cast(value.buf, C.POINTER(C.c_float)), shape=(attr.n_elems,))
                result.append(array.copy().reshape(list(attr.dims[:attr.n_dims])))
            return result
        finally:
            checked(self.lib.rknn_outputs_release(self.context, 9, outputs), '释放输出')

    def close(self):
        if self.context.value:
            self.lib.rknn_destroy(self.context)
            self.context.value = 0
