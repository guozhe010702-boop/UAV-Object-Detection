"""Trusted PT -> RK-optimized ONNX -> RKNN, CPU-only conversion in pinned Linux."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import time

ZH = {'pedestrian': '行人', 'people': '人员', 'bicycle': '自行车', 'car': '小汽车',
      'van': '面包车', 'truck': '卡车', 'tricycle': '三轮车', 'awning-tricycle': '带篷三轮车',
      'bus': '公交车', 'motor': '摩托车', 'others': '其他（待验证）'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pt', type=Path, required=True, help='trusted local checkpoint only')
    p.add_argument('--output', type=Path, required=True, help='new, empty artifact directory')
    p.add_argument('--int8', action='store_true')
    p.add_argument('--calibration', type=Path, help='representative UAV images; required for INT8')
    p.add_argument('--onnx-only', action='store_true')
    a = p.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        p.error('Run in the pinned x86_64 Linux conversion container, not on the RK3588')
    if not a.pt.is_file() or a.pt.suffix != '.pt':
        p.error('PT checkpoint does not exist')
    if a.output.exists() and any(a.output.iterdir()):
        p.error('Use a new output directory; never overwrite validated artifacts')
    if a.int8 and (not a.calibration or not a.calibration.is_dir()):
        p.error('INT8 requires representative calibration images')
    a.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    receipt = {'stage': 'starting', 'source_sha256': sha256(a.pt), 'input_size': [640, 640],
               'hardware_validation': False, 'npu_inference_performed': False}
    try:
        import torch
        import onnx
        import numpy as np
        from ultralytics import YOLO
        from ultralytics.nn.modules.head import Detect
        torch.set_num_threads(4)
        wrapped = YOLO(str(a.pt), task='detect')
        names = wrapped.names
        classes = [str(names[i]) for i in range(len(names))] if isinstance(names, dict) else list(names)
        model = wrapped.model.cpu().float().eval()
        model.fuse()
        heads = 0
        for module in model.modules():
            if type(module) is Detect:
                module.export, module.format, module.dynamic = True, 'rknn', False
                heads += 1
        if heads != 1:
            raise ValueError('Expected a standard YOLO11 detection head; refusing incompatible task')
        tensor = torch.zeros(1, 3, 640, 640)
        with torch.inference_mode():
            outputs = model(tensor)
        if not isinstance(outputs, (tuple, list)) or len(outputs) != 9:
            raise ValueError('Export did not select the RK-optimized nine-head path')
        expected = []
        for grid in (80, 40, 20):
            expected += [[1, 64, grid, grid], [1, len(classes), grid, grid], [1, 1, grid, grid]]
        if [list(x.shape) for x in outputs] != expected:
            raise ValueError('Output tensors do not match the declared deployment contract')
        names_out = ['branch_' + str(i) for i in range(9)]
        onnx_file = a.output / 'model.onnx'
        torch.onnx.export(model, tensor, str(onnx_file), opset_version=12,
                          input_names=['images'], output_names=names_out, do_constant_folding=True)
        graph = onnx.load(str(onnx_file))
        onnx.checker.check_model(graph)
        graph_shapes = [[d.dim_value for d in item.type.tensor_type.shape.dim] for item in graph.graph.output]
        if graph_shapes != expected:
            raise ValueError('Exported ONNX shapes differ from the PyTorch result')
        # Compare numeric branch outputs before converting the graph to RKNN.
        import onnxruntime as ort
        session = ort.InferenceSession(str(onnx_file), providers=['CPUExecutionProvider'])
        random_input = np.random.default_rng(0).random((1, 3, 640, 640), dtype=np.float32)
        with torch.inference_mode():
            reference = [x.numpy() for x in model(torch.from_numpy(random_input))]
        onnx_outputs = session.run(None, {'images': random_input})
        max_error = max(float(np.max(np.abs(x - y))) for x, y in zip(reference, onnx_outputs))
        for x, y in zip(reference, onnx_outputs):
            np.testing.assert_allclose(x, y, atol=0.002, rtol=0.002)
        receipt.update(stage='onnx_validated', classes=classes, onnx_sha256=sha256(onnx_file),
                       onnx_max_absolute_error=max_error)
        (a.output / 'classes.json').write_text(json.dumps({'classes': classes, 'labels_zh': [ZH.get(x, x) for x in classes]}, ensure_ascii=False, indent=2), encoding='utf-8')
        if a.onnx_only:
            return
        from rknn.api import RKNN
        rknn = RKNN(verbose=False)
        try:
            result = rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], target_platform='rk3588')
            if result not in (None, 0):
                raise RuntimeError('RKNN config failed: ' + str(result))
            result = rknn.load_onnx(model=str(onnx_file))
            if result != 0:
                raise RuntimeError('RKNN ONNX import failed: ' + str(result))
            calibration = None
            if a.int8:
                images = sorted(p.resolve() for p in a.calibration.rglob('*') if p.suffix.lower() in ('.jpg', '.jpeg', '.png') and p.is_file())
                if len(images) < 20:
                    raise ValueError('Use at least 20 representative UAV calibration images; no synthetic substitute')
                calibration = a.output / 'calibration.txt'
                calibration.write_text('\n'.join(str(p) for p in images) + '\n')
            result = rknn.build(do_quantization=a.int8, dataset=str(calibration) if calibration else None)
            if result != 0:
                raise RuntimeError('RKNN build failed: ' + str(result))
            rknn_file = a.output / 'model.rknn'
            result = rknn.export_rknn(str(rknn_file))
            if result != 0:
                raise RuntimeError('RKNN export failed: ' + str(result))
        finally:
            rknn.release()
        commit = subprocess.check_output(['git', '-C', '/opt/rk-yolo11', 'rev-parse', 'HEAD'], text=True).strip()
        manifest = {'schema_version': 1, 'name': 'VisDrone YOLO11n', 'architecture': 'yolo11n',
                    'platform': 'rk3588', 'input_size': [640, 640], 'classes': classes,
                    'labels_zh': [ZH.get(x, x) for x in classes], 'output_layout': 'rockchip-yolo11-dfl-9',
                    'precision': 'int8' if a.int8 else 'fp16', 'sha256': sha256(rknn_file),
                    'onnx_sha256': sha256(onnx_file), 'source': 'https://huggingface.co/dronefreak/visdrone-yolo11n',
                    'license': 'AGPL-3.0; see model card and VisDrone dataset terms',
                    'exported_at': datetime.now(timezone.utc).isoformat(), 'validated_on_board': False,
                    'outputs': [{'name': name, 'shape': shape} for name, shape in zip(names_out, expected)],
                    'preprocessing': {'color': 'RGB', 'layout': 'NHWC', 'host_dtype': 'uint8',
                                      'letterbox': True, 'pad_value': 0, 'mean': [0, 0, 0], 'std': [255, 255, 255]},
                    'conversion': {'exporter_commit': commit, 'torch': torch.__version__, 'onnx': onnx.__version__,
                                   'rknn_toolkit2': version('rknn-toolkit2'), 'source_pt_sha256': receipt['source_sha256'],
                                   'onnx_max_absolute_error': max_error, 'seconds': time.monotonic() - started}}
        (a.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        receipt.update(stage='rknn_exported_not_board_validated', rknn_sha256=manifest['sha256'])
    except BaseException as error:
        receipt.update(stage='failed', error=str(error))
        raise
    finally:
        receipt['seconds'] = time.monotonic() - started
        (a.output / 'conversion-result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(receipt, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
