"""YOLO11 Rockchip nine-output DFL head. All thresholds are per actual frame."""
import numpy as np
from PIL import Image


def letterbox(image, size=640):
    width, height = image.size
    ratio = min(size / width, size / height)
    resized = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    left, top = (size - resized[0]) // 2, (size - resized[1]) // 2
    canvas = Image.new('RGB', (size, size), (0, 0, 0))
    canvas.paste(image.resize(resized, Image.Resampling.BILINEAR), (left, top))
    # Use actual rounded resize factors when restoring coordinates.
    return np.asarray(canvas, dtype=np.uint8).copy(), (resized[0] / width, resized[1] / height, left, top)


def nms(boxes, scores, threshold, maximum=300):
    order = np.argsort(-scores, kind='stable')
    areas = np.maximum(0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0, boxes[:, 3] - boxes[:, 1])
    keep = []
    while len(order) and len(keep) < maximum:
        i = order[0]
        keep.append(i)
        rest = order[1:]
        xy1 = np.maximum(boxes[i, :2], boxes[rest, :2])
        xy2 = np.minimum(boxes[i, 2:], boxes[rest, 2:])
        wh = np.maximum(0, xy2 - xy1)
        inter = wh[:, 0] * wh[:, 1]
        union = areas[i] + areas[rest] - inter
        overlap = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = rest[overlap <= threshold]
    return keep


def decode(outputs, classes, transform, original_size, confidence=.25, iou=.45):
    if len(outputs) != 9:
        raise ValueError('YOLO11 必须返回 9 个输出')
    all_boxes, all_scores, all_ids = [], [], []
    for i, grid in enumerate((80, 40, 20)):
        reg, probs, sums = outputs[i * 3:i * 3 + 3]
        if reg.shape != (1, 64, grid, grid) or probs.shape != (1, len(classes), grid, grid):
            raise ValueError('运行时输出形状与模型清单不一致')
        scores = probs[0].max(axis=0)
        labels = probs[0].argmax(axis=0)
        # Class probabilities are already sigmoid; score_sum is not objectness.
        ys, xs = np.where(np.isfinite(scores) & (scores >= confidence))
        if not len(xs):
            continue
        logits = reg[0].reshape(4, 16, grid, grid)[:, :, ys, xs]
        distribution = np.exp(logits - logits.max(axis=1, keepdims=True))
        distribution /= distribution.sum(axis=1, keepdims=True)
        distances = (distribution * np.arange(16, dtype=np.float32)[None, :, None]).sum(axis=1)
        stride = 640 / grid
        centers = np.stack((xs + .5, ys + .5))
        boxes = np.concatenate((centers - distances[:2], centers + distances[2:]), axis=0).T * stride
        valid = np.isfinite(boxes).all(axis=1)
        all_boxes.append(boxes[valid]); all_scores.append(scores[ys, xs][valid]); all_ids.append(labels[ys, xs][valid])
    if not all_boxes:
        return []
    boxes, scores, ids = np.concatenate(all_boxes), np.concatenate(all_scores), np.concatenate(all_ids)
    # Bound worst-case NMS work without allocating an O(N^2) matrix.
    top = np.argsort(-scores, kind='stable')[:3000]
    boxes, scores, ids = boxes[top], scores[top], ids[top]
    keep = []
    for category in np.unique(ids):
        indices = np.where(ids == category)[0]
        keep.extend(indices[nms(boxes[indices], scores[indices], iou)])
    keep = sorted(keep, key=lambda k: -scores[k])[:300]
    sx, sy, left, top = transform
    boxes[:, (0, 2)] = (boxes[:, (0, 2)] - left) / sx
    boxes[:, (1, 3)] = (boxes[:, (1, 3)] - top) / sy
    boxes[:, (0, 2)] = boxes[:, (0, 2)].clip(0, original_size[0])
    boxes[:, (1, 3)] = boxes[:, (1, 3)].clip(0, original_size[1])
    return [{'class_id': int(ids[k]), 'class': classes[ids[k]], 'confidence': float(scores[k]),
             'box': [round(float(x), 2) for x in boxes[k]]} for k in keep
            if boxes[k, 2] > boxes[k, 0] and boxes[k, 3] > boxes[k, 1]]
