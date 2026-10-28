"""Board-only full validation predictions. Does not open a camera or generate mock results."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    import numpy as np
    from PIL import Image
    from uav_app.postprocess import decode, letterbox
    from uav_app.rknn_backend import RKNN
    from uav_app.inference_io import annotation
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=ROOT / 'runtime/lib/librknnrt.so')
    args = parser.parse_args()
    index = json.loads((args.dataset / 'index.json').read_text(encoding='utf-8'))
    manifest = json.loads((args.bundle / 'manifest.json').read_text(encoding='utf-8'))
    assert len(index['validation']) == 548
    assert not set(index['validation']) & set(index['calibration'])
    args.output.mkdir(parents=True, exist_ok=True)
    model = RKNN(args.bundle / 'model.rknn', manifest, args.library)
    results, times = [], []
    start = time.monotonic()
    try:
        for i, filename in enumerate(index['validation']):
            path = args.dataset / 'images' / filename
            assert hashlib.sha256(path.read_bytes()).hexdigest() == index['images'][filename]['sha256']
            with Image.open(path) as original:
                image = original.convert('RGB'); original_size = image.size
            # Match the deployed still-image path: preview -> letterbox -> model.
            width = min(1280, image.width)
            height = max(2, round(image.height * width / image.width / 2) * 2)
            image = image.resize((width, height), Image.Resampling.BILINEAR)
            rgb, transform = letterbox(image)
            before = time.monotonic();outputs = model.infer(rgb)
            times.append((time.monotonic() - before) * 1000)
            detections = decode(outputs, manifest['classes'], transform, image.size, confidence=.001,
                                iou=.65, max_detections=500)
            for detection in detections:
                x1, y1, x2, y2 = detection['box']
                results.append({'image_id': i + 1, 'category_id': detection['class_id'] + 1,
                    'bbox': [x1 * original_size[0] / width, y1 * original_size[1] / height,
                             (x2 - x1) * original_size[0] / width, (y2 - y1) * original_size[1] / height],
                    'score': detection['confidence']})
            if i < 5:
                visual = [d for d in detections if d['confidence'] >= .25]
                (args.output / ('sample-%s.jpg' % (i + 1))).write_bytes(annotation(image, visual,
                    manifest.get('labels_zh') or manifest['classes'], manifest['classes']))
            if (i + 1) % 50 == 0:print('%s: %s/548' % (manifest['precision'], i + 1), flush=True)
        (args.output / 'predictions.json').write_text(json.dumps(results), encoding='utf-8')
        receipt = {'model_sha256': manifest['sha256'], 'dataset_revision': index['revision'],
                   'validation_images': len(index['validation']), 'calibration_images': len(index['calibration']),
                   'disjoint': True, 'hardware': model.info, 'precision': manifest['precision'],
                   'inference_p50_ms': float(np.percentile(times[1:], 50)),
                   'inference_p95_ms': float(np.percentile(times[1:], 95)),
                   'elapsed_seconds': time.monotonic() - start, 'candidate_boxes': len(results),
                   'confidence': .001, 'nms_iou': .65, 'max_detections': 500,
                   'preprocessing': 'RGB, preview <=1280 width, 640 black letterbox, CPU bilinear resize'}
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt), flush=True)
    finally:
        model.close()


if __name__ == '__main__':
    main()
