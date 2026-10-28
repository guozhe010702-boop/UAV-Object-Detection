"""COCO-style scoring of board predictions; explicitly not official VisDrone Matlab evaluation."""
import argparse
import json
from pathlib import Path
import numpy as np

ALIASES = {'pedestrians': 'pedestrian', 'awning_tricycle': 'awning-tricycle'}


def category_name(value):
    name = ALIASES.get(value, value)
    allowed = {'pedestrian', 'people', 'bicycle', 'car', 'van', 'truck', 'tricycle',
               'awning-tricycle', 'bus', 'motor', 'ignore_regions', 'others'}
    if name not in allowed:
        raise ValueError('Unknown ground-truth label: ' + value)
    return name


def ignored_fraction(box, regions):
    x, y, w, h = box
    if w <= 0 or h <= 0:return 1.
    # Official region files can overlap; maximum region coverage is used here,
    # disclosed in the protocol. This is not a pixel-union ignore-mask evaluator.
    return max((max(0, min(x + w, rx + rw) - max(x, rx)) *
                max(0, min(y + h, ry + rh) - max(y, ry)) / (w * h)
                for rx, ry, rw, rh in regions), default=0.)


def main():
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    index = json.loads(args.index.read_text(encoding='utf-8'))
    images, annotations, regions = [], [], {}
    for i, filename in enumerate(index['validation'], 1):
        row = index['images'][filename];w, h = row['width'], row['height']
        images.append({'id': i, 'width': w, 'height': h, 'file_name': filename})
        regions[i] = []
        for det in row['detections']:
            x, y, bw, bh = det['bounding_box'];box = [x * w, y * h, bw * w, bh * h]
            if det['label'] in ('ignore_regions', 'others'):
                regions[i].append(box)
        for det in row['detections']:
            label = category_name(det['label'])
            if label not in index['classes']:continue
            x, y, bw, bh = det['bounding_box'];box = [x * w, y * h, bw * w, bh * h]
            if ignored_fraction(box, regions[i]) > .5:continue
            annotations.append({'id': len(annotations) + 1, 'image_id': i,
                'category_id': index['classes'].index(label) + 1,
                'bbox': box, 'area': box[2] * box[3], 'iscrowd': 0})
    raw = json.loads(args.predictions.read_text(encoding='utf-8'))
    predictions = [r for r in raw if r['category_id'] <= 10 and ignored_fraction(r['bbox'], regions[r['image_id']]) <= .5]
    coco = COCO();coco.dataset = {'images': images, 'annotations': annotations,
        'categories': [{'id': i + 1, 'name': c} for i, c in enumerate(index['classes'])]}
    coco.createIndex()
    result = coco.loadRes(predictions)
    evaluator = COCOeval(coco, result, 'bbox');evaluator.params.maxDets = [1, 10, 500]
    evaluator.evaluate();evaluator.accumulate()
    precision = evaluator.eval['precision'][:, :, :, 0, 2]
    valid = precision[precision >= 0]
    p50 = precision[0];p75 = precision[5]
    metrics = {'map50_95': float(valid.mean()), 'map50': float(p50[p50 >= 0].mean()),
               'map75': float(p75[p75 >= 0].mean()), 'per_class': {}}
    for i, name in enumerate(index['classes']):
        p = precision[:, :, i];p50 = precision[0, :, i]
        metrics['per_class'][name] = {'map50_95': float(p[p >= 0].mean()) if (p >= 0).any() else None,
                                     'ap50': float(p50[p50 >= 0].mean()) if (p50 >= 0).any() else None,
                                     'gt': sum(x['category_id'] == i + 1 for x in annotations)}
    metrics.update(images=len(images), annotated_targets=len(annotations), scored_predictions=len(predictions),
                   ignored_predictions=len(raw) - len(predictions), classes=10, max_detections=500,
                   dataset_revision=index['revision'], scope='Complete VisDrone val split, COCO-style; not official challenge metric',
                   ignore_protocol='Exclude ignored_regions/others and predictions/GT covered >50% by any one ignored box; no pixel-union ignore map',
                   thresholds='confidence .001, classwise NMS .65, IoU .50:.05:.95, 101 recall points',
                   others='Not scored; no reliable trained category evidence',
                   category_aliases=ALIASES,
                   leakage_note='Calibration uses train only; public checkpoint training provenance is upstream-reported, not independently audited')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics))


if __name__ == '__main__':
    main()
