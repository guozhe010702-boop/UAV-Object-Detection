"""One-second real device sampling for a fixed uninterrupted run; writes CSV + verdict.

Run on the board using its private venv. This monitor never starts/repeats controls.
"""
import argparse
import csv
import json
from pathlib import Path
import statistics
import time
import urllib.request

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/userdata/uav-object-detection'))
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--minimum-fps', type=float, default=25.)
    args = parser.parse_args()
    if args.seconds < 1:parser.error('seconds must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    token = (args.root / 'data/admin-token.txt').read_text().strip()
    def status():
        req = urllib.request.Request('http://127.0.0.1:8088/api/status', headers={'Authorization': 'Bearer ' + token})
        return json.load(urllib.request.urlopen(req, timeout=5))
    initial = status()
    if not initial['inference_connected']:raise RuntimeError('Start a healthy real source before monitoring')
    run_id = initial['run_id'];pid = initial['worker_pid'];process = psutil.Process(pid)
    process.cpu_percent(None)
    # Warm-up is excluded explicitly; the entire measured duration follows this baseline.
    start = time.monotonic();deadline = start + args.seconds
    baseline_count = initial['frames_processed'];samples = [];errors = []
    fields = ['wall_time', 'elapsed_s', 'run_id', 'frame_id', 'frames_processed', 'capture_fps', 'processing_fps',
              'inference_ms', 'preprocess_ms', 'postprocess_ms', 'annotation_ms', 'frames_dropped',
              'cpu_percent', 'memory_percent', 'worker_cpu_one_core_percent', 'worker_rss_bytes',
              'temperature_c', 'npu0', 'npu1', 'npu2', 'stale', 'error']
    with (args.output / 'samples.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields);writer.writeheader()
        next_sample = start
        previous_count, previous_clock = baseline_count, start
        while time.monotonic() < deadline:
            now = time.monotonic()
            try:
                value = status();resource = value['resources'];npu = resource.get('npu_percent') or [None] * 3
                if value.get('run_id') != run_id or value.get('worker_pid') != pid:
                    raise RuntimeError('Supervised run changed; this is not an uninterrupted test')
                if not value['inference_connected'] or value.get('stale'):
                    raise RuntimeError('Source stopped producing fresh frames')
                current = time.monotonic()
                rate = (value['frames_processed'] - previous_count) / (current - previous_clock) if current > previous_clock else None
                previous_count, previous_clock = value['frames_processed'], current
                row = dict(wall_time=time.time(), elapsed_s=current - start, run_id=run_id,
                    frame_id=value['frame_id'], frames_processed=value['frames_processed'],
                    capture_fps=value.get('capture_fps'), processing_fps=rate,
                    inference_ms=value.get('inference_ms'), preprocess_ms=value.get('preprocess_ms'),
                    postprocess_ms=value.get('postprocess_ms'), annotation_ms=value.get('annotation_ms'),
                    frames_dropped=value.get('frames_dropped'), cpu_percent=resource.get('cpu_percent'),
                    memory_percent=resource.get('memory_percent'), worker_cpu_one_core_percent=process.cpu_percent(None),
                    worker_rss_bytes=process.memory_info().rss, temperature_c=resource.get('temperature_c'),
                    npu0=npu[0], npu1=npu[1], npu2=npu[2], stale=False, error=value.get('error'))
                samples.append(row);writer.writerow(row);file.flush()
            except Exception as error:
                errors.append({'at': time.time(), 'error': str(error)})
                writer.writerow({'wall_time': time.time(), 'elapsed_s': time.monotonic() - start,
                                 'run_id': run_id, 'error': str(error)});file.flush()
            next_sample += 1
            delay = min(next_sample, deadline) - time.monotonic()
            if delay > 0:time.sleep(delay)
        final = status();end = time.monotonic()
    elapsed = end - start
    average = (final['frames_processed'] - baseline_count) / elapsed
    rss = [x['worker_rss_bytes'] for x in samples]
    receipt = {'requested_seconds': args.seconds, 'elapsed_seconds': elapsed, 'sample_count': len(samples),
        'run_id': run_id, 'worker_pid': pid, 'source': final['source'], 'npu': final['npu'],
        'model': final['model']['manifest']['name'], 'model_sha256': final['model']['manifest']['sha256'],
        'processed_frames': final['frames_processed'] - baseline_count, 'average_processing_fps': average,
        'mean_inference_ms': statistics.mean(x['inference_ms'] for x in samples) if samples else None,
        'mean_cpu_percent': statistics.mean(x['cpu_percent'] for x in samples if x['cpu_percent'] is not None) if samples else None,
        'max_temperature_c': max(x['temperature_c'] for x in samples if x['temperature_c'] is not None) if samples else None,
        'worker_rss_first': rss[0] if rss else None, 'worker_rss_last': rss[-1] if rss else None,
        'worker_rss_max': max(rss) if rss else None, 'errors': errors,
        'stability_passed': not errors and len(samples) >= .99 * args.seconds and final.get('run_id') == run_id,
        'fps_target': args.minimum_fps, 'performance_passed': average >= args.minimum_fps,
        'scope': 'Actual source + NPU + postprocess + annotated JPEG; browser separately measured. No restart/retry of controls.'}
    (args.output / 'result.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
