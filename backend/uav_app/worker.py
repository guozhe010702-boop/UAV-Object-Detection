"""Supervised process: RKNN NPU + bounded source reader + asynchronous records."""
from collections import Counter, deque
import json
from pathlib import Path
import queue
import signal
import sys
import threading
import time
import traceback

import numpy as np

from .inference_io import Capture, annotation, atomic_json, actual_camera_format
from .postprocess import decode, letterbox
from .rknn_backend import RKNN
from .store import Store
from .source_auth import read_credentials, public_source
from .preprocess import Preprocessor


def run(config):
    folder = Path(config['run_dir'])
    store = Store(config['data_dir'])
    manifest, settings = config['manifest'], config['settings']
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    state = {'state': 'starting', 'frame_id': None, 'processing_fps': None, 'current_counts': None,
             'inference_ms': None, 'frames_processed': 0, 'source': public_source(config['source']), 'error': None,
             'run_id': folder.name, 'updated_at': time.time()}

    def publish():
        state['updated_at'] = time.time()
        atomic_json(folder / 'status.json', state)

    publish()
    model = capture = preprocessor = None
    record_queue = queue.Queue(maxsize=1)
    record_stop = threading.Event()
    record_error = [None]

    def save_records():
        while not record_stop.is_set() or not record_queue.empty():
            try:
                row, jpeg = record_queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                store.add_detection(row, jpeg)
                record_error[0] = None
            except Exception as error:
                record_error[0] = str(error)
            finally:
                record_queue.task_done()

    recorder = threading.Thread(target=save_records, name='uav-records', daemon=True)
    recorder.start()
    try:
        model = RKNN(config['model_path'], manifest, config['library'])
        state['npu'] = model.info
        # Mark execution only after a real successful run, not merely after loading.
        with (folder / 'capture.log').open('ab', buffering=0) as log:
            capture = Capture(config['source'], settings['preview_width'], log,
                              read_credentials(store.root, config['source']['name']))
            preprocessor = Preprocessor(capture.frames)
            state['preview_size'] = list(capture.size)
            count, baseline, previous, last_record = 0, time.monotonic(), 0, -float('inf')
            previous_received = 0
            infer_samples, age_samples = deque(maxlen=120), deque(maxlen=120)
            while not stop.is_set():
                frame = preprocessor.frames.take(timeout=12)
                if frame is None:
                    state['state'] = 'completed'; break
                _, _, prepared = frame
                frame_id, acquired, image, rgb, transform, preprocess_ms = prepared
                if count == 0 and config['source']['kind'] in ('imx415', 'usb'):
                    state['source']['actual_mode'] = actual_camera_format(config['source']['name'])
                before = time.monotonic()
                outputs = model.infer(rgb)
                infer_ms = (time.monotonic() - before) * 1000
                post = time.monotonic()
                detections = decode(outputs, manifest['classes'], transform, image.size, settings['confidence'], settings['iou'])
                post_ms = (time.monotonic() - post) * 1000
                labels = manifest.get('labels_zh') or manifest['classes']
                annotation_start = time.monotonic()
                jpeg = annotation(image, detections, labels, manifest['classes'])
                annotation_ms = (time.monotonic() - annotation_start) * 1000
                now = time.monotonic()
                count += 1; infer_samples.append(infer_ms); age_samples.append((now - acquired) * 1000)
                if now - baseline >= 1:
                    state['processing_fps'] = (count - previous) / (now - baseline)
                    state['capture_fps'] = (capture.frames.received - previous_received) / (now - baseline)
                    previous_received = capture.frames.received
                    previous, baseline = count, now
                    # The capture log is diagnostic only. Bound tmpfs growth on long runs.
                    path = folder / 'capture.log'
                    if path.stat().st_size > 1024 * 1024:
                        with path.open('r+b') as diagnostic:
                            diagnostic.seek(-128 * 1024, 2); tail = diagnostic.read()
                            diagnostic.seek(0); diagnostic.write(tail); diagnostic.truncate()
                counts = dict(Counter(labels[x['class_id']] for x in detections))
                state.update(state='running', frame_id=frame_id, frames_processed=count,
                    frames_received=capture.frames.received,
                    frames_dropped=capture.frames.dropped + preprocessor.frames.dropped,
                    capture_queue_drops=capture.frames.dropped, preprocess_queue_drops=preprocessor.frames.dropped,
                    current_counts=counts, objects=len(detections), detections=detections,
                    inference_ms=infer_ms, postprocess_ms=post_ms, preview_updated_at=time.time(),
                    preprocess_ms=preprocess_ms, annotation_ms=annotation_ms,
                    inference_p50_ms=float(np.percentile(infer_samples, 50)), inference_p95_ms=float(np.percentile(infer_samples, 95)),
                    frame_age_p95_ms=float(np.percentile(age_samples, 95)), record_error=record_error[0])
                # JPEG and its boxes form one immutable blob. No later frame can reuse old boxes.
                temporary = folder / 'frame.tmp'
                # Publish identity and JPEG together, so a browser never counts
                # the same image twice or associates new pixels with an old ID.
                temporary.write_bytes(frame_id.to_bytes(8, 'big') + jpeg)
                temporary.replace(folder / 'frame.bin')
                publish()
                if count == 1:
                    store.mark_model_validated(config['model_id'], model.info)
                if now - last_record >= settings['record_interval']:
                    try:
                        record_queue.put_nowait(({'at': time.time(), 'model_id': config['model_id'],
                            'source': config['source']['name'], 'counts': counts, 'objects': len(detections),
                            'inference_ms': infer_ms}, jpeg))
                        last_record = now
                    except queue.Full:
                        state['records_skipped'] = state.get('records_skipped', 0) + 1
            if stop.is_set():
                state['state'] = 'stopped'
    except BaseException as error:
        if stop.is_set():
            state.update(state='stopped', error=None)
        else:
            state.update(state='error', error=str(error))
            traceback.print_exc()
    finally:
        if capture:
            capture.close()
        if preprocessor:
            preprocessor.close()
        if model:
            model.close()
        record_stop.set(); recorder.join(timeout=5)
        state['record_error'] = record_error[0]
        state['processing_fps'] = 0 if state['frames_processed'] else None
        publish()


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
