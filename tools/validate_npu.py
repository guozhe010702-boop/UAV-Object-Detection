"""Run on the board with its private venv. Outputs are real RKNN measurements."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    import numpy as np
    from PIL import Image
    from uav_app.postprocess import letterbox, decode
    from uav_app.rknn_backend import RKNN
    from uav_app.inference_io import annotation
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=ROOT / 'runtime/lib/librknnrt.so')
    parser.add_argument('--runs', type=int, default=20, choices=range(1, 101))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.bundle / 'manifest.json').read_text(encoding='utf-8'))
    with Image.open(args.image) as source:
        image = source.convert('RGB')
    rgb, transform = letterbox(image)
    model = RKNN(args.bundle / 'model.rknn', manifest, args.library)
    try:
        times = []
        for i in range(args.runs + 1):
            start = time.monotonic();outputs = model.infer(rgb)
            if i:times.append((time.monotonic() - start) * 1000)
        detections = decode(outputs, manifest['classes'], transform, image.size)
        np.savez_compressed(args.output / 'npu-outputs.npz', rgb=rgb,
                            **{'out%s' % i: x for i, x in enumerate(outputs)})
        (args.output / 'detected.jpg').write_bytes(annotation(image, detections,
            manifest.get('labels_zh') or manifest['classes'], manifest['classes']))
        report = {'hardware': model.info, 'source_size': list(image.size), 'runs': args.runs,
                  'warmup_runs': 1, 'inference_p50_ms': float(np.percentile(times, 50)),
                  'inference_p95_ms': float(np.percentile(times, 95)), 'detections': detections,
                  'scope': 'NPU inference only, not camera/end-to-end FPS or dataset accuracy'}
        (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'detections'}, ensure_ascii=True))
    finally:
        model.close()


if __name__ == '__main__':
    main()
