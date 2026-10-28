"""Unannotated consecutive real UAV frames -> 25 fps test container, no synthesized frames."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = '3330e2096cf866ec0a70ae663681b6a5c8a967d9'
BASE = 'https://huggingface.co/datasets/Voxel51/visdrone-mot/resolve/' + REVISION + '/'


def main():
    from prepare_visdrone import download
    cache = ROOT / '.cache/mot';cache.mkdir(parents=True, exist_ok=True)
    samples = cache / 'samples.json'
    if not samples.exists():download(BASE + 'samples.json', samples)
    rows = json.loads(samples.read_text(encoding='utf-8'))['samples']
    scene = 'uav0000137_00458_v'
    chosen = sorted([x for x in rows if x['scene_id'] == scene], key=lambda x: x['frame_number'])
    assert len(chosen) == 233
    assert [r['frame_number'] for r in chosen] == list(range(1, 234))
    folder = ROOT / 'datasets/aerial-clip';folder.mkdir(parents=True, exist_ok=True)
    def get(row):
        target = folder / ('%07d.jpg' % row['frame_number'])
        if not target.exists():download(BASE + row['filepath'], target)
        assert target.stat().st_size == row['metadata']['size_bytes']
        return {'source': row['filepath'], 'frame': row['frame_number'],
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    with ThreadPoolExecutor(max_workers=8) as pool:receipt = list(pool.map(get, chosen))
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('ffmpeg not found on PC')
    video = folder / 'VisDrone_MOT_real_sequence_25fps.mp4'
    subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-framerate', '25', '-start_number', '1',
                    '-i', str(folder / '%07d.jpg'), '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                    '-pix_fmt', 'yuv420p', str(video)], check=True)
    info = {'source': 'Voxel51/visdrone-mot', 'revision': REVISION, 'scene': scene, 'frames': len(chosen),
            'playback_fps': 25, 'duration_seconds': len(chosen) / 25,
            'scope': 'Consecutive real frames, no duplicated/interpolated content; 25 fps is selected playback timing, not a sensor-fps claim',
            'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'images': receipt}
    (folder / 'receipt.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in info.items() if k != 'images'}))


if __name__ == '__main__':
    main()
