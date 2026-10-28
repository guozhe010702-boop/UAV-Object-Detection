"""Pinned public VisDrone: train-only calibration and the complete 548-image val split."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import random
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = '3c3b9e9bd44c91121c1fc19fce428f0e6b71bba2'
BASE = 'https://huggingface.co/datasets/Voxel51/VisDrone2019-DET/resolve/' + REVISION + '/'
CLASSES = ['pedestrian', 'people', 'bicycle', 'car', 'van', 'truck', 'tricycle', 'awning-tricycle', 'bus', 'motor']


def download(url, target):
    for attempt in range(4):
        try:
            temporary = target.with_suffix(target.suffix + '.part')
            with urllib.request.urlopen(url, timeout=60) as source, temporary.open('wb') as dest:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:break
                    dest.write(block)
            temporary.replace(target)
            return
        except OSError:
            if attempt == 3:raise
            time.sleep(attempt + 1)


def main():
    from PIL import Image
    sys.path.insert(0, str(ROOT / 'backend'))
    from uav_app.postprocess import letterbox
    folder = ROOT / 'datasets/visdrone'
    folder.mkdir(parents=True, exist_ok=True)
    samples = ROOT / '.cache/visdrone-samples.json'
    if not samples.is_file():download(BASE + 'samples.json', samples)
    rows = json.loads(samples.read_text(encoding='utf-8'))['samples']
    validation = sorted((r for r in rows if 'val' in r['tags']), key=lambda r: r['filepath'])
    assert len(validation) == 548, 'Unexpected dataset revision/split'
    train = sorted((r for r in rows if 'train' in r['tags']), key=lambda r: r['filepath'])
    # Spread selected calibration scenes rather than taking adjacent video frames.
    random.Random(3588).shuffle(train)
    calibration, scenes = [], set()
    for row in train:
        scene = Path(row['filepath']).stem.split('_')[0]
        if scene not in scenes:
            scenes.add(scene);calibration.append(row)
        if len(calibration) == 64:break
    assert len(calibration) == 64
    assert not ({r['filepath'] for r in calibration} & {r['filepath'] for r in validation})
    for name in ('images', 'calibration'):(folder / name).mkdir(exist_ok=True)
    selected = calibration + validation

    def prepare(row):
        filename = Path(row['filepath']).name
        assert filename.endswith('.jpg') and '/' not in filename
        path = folder / 'images' / filename
        if not path.is_file() or path.stat().st_size != row['metadata']['size_bytes']:
            download(BASE + row['filepath'], path)
        raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            width, height = image.size
            assert (width, height) == (row['metadata']['width'], row['metadata']['height'])
        return {'filename': filename, 'sha256': raw_hash, 'width': width, 'height': height,
                'split': 'train' if 'train' in row['tags'] else 'val',
                'detections': row['ground_truth']['detections']}

    result = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(prepare, r): r['filepath'] for r in selected}
        for n, future in enumerate(as_completed(jobs), 1):
            item = future.result();result[item['filename']] = item
            if n % 50 == 0:print('Downloaded/verified %s/%s' % (n, len(selected)), flush=True)
    for row in calibration:
        source = folder / 'images' / Path(row['filepath']).name
        with Image.open(source) as image:rgb, _ = letterbox(image.convert('RGB'))
        Image.fromarray(rgb).save(folder / 'calibration' / (source.stem + '.png'))
    index = {'source': 'Voxel51/VisDrone2019-DET', 'revision': REVISION,
             'metadata_sha256': hashlib.sha256(samples.read_bytes()).hexdigest(),
             'classes': CLASSES, 'calibration': [Path(r['filepath']).name for r in calibration],
             'validation': [Path(r['filepath']).name for r in validation], 'images': result,
             'license': 'VisDrone Attribution-NonCommercial-ShareAlike; local research validation only',
             'evaluation_scope': 'Complete val split; COCO-style metrics with documented ignore handling; not official challenge submission'}
    (folder / 'index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'trainCalibration': len(calibration), 'validation': len(validation),
                      'revision': REVISION, 'index': str(folder / 'index.json')}), flush=True)


if __name__ == '__main__':
    main()
