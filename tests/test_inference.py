"""Numerical/concurrency contracts. Fixtures do not claim hardware inference."""
import io
import json
import threading
import time

import numpy as np
from PIL import Image
import pytest

from uav_app.inference_io import LatestFrames, read_exact, atomic_json, source_spec
from uav_app.postprocess import letterbox, decode, nms
from uav_app.engine import Engine
from uav_app.store import Store


def outputs():
    result = []
    for grid in (80, 40, 20):
        # DFL mass at distance 1 cell in each direction.
        reg = np.full((1, 4, 16, grid, grid), -30, dtype=np.float32)
        reg[:, :, 1] = 30
        result += [reg.reshape(1, 64, grid, grid), np.zeros((1, 2, grid, grid), dtype=np.float32),
                   np.ones((1, 1, grid, grid), dtype=np.float32)]
    return result


def test_letterbox_rgb_black_and_rounded_inverse():
    image = Image.new('RGB', (1000, 501), (231, 32, 17))
    rgb, transform = letterbox(image)
    assert rgb.shape == (640, 640, 3) and rgb.dtype == np.uint8
    assert rgb[0, 0].tolist() == [0, 0, 0]
    assert rgb[320, 320].tolist() == [231, 32, 17]
    assert transform == (.64, 321 / 501, 0, 159)


def test_dfl_sigmoid_scores_and_inverse_coordinates():
    heads = outputs()
    heads[1][0, 1, 40, 40] = .8
    # score_sum must not be multiplied into class confidence.
    heads[2].fill(0)
    detections = decode(heads, ['car', 'people'], (.5, .5, 0, 160), (1280, 640))
    assert len(detections) == 1
    result = detections[0]
    assert result['class'] == 'people'
    assert result['box'] == [632, 312, 664, 344]
    assert result['confidence'] == pytest.approx(.8)


def test_classwise_nms_empty_invalid_and_candidate_cap():
    assert decode(outputs(), ['a', 'b'], (1, 1, 0, 0), (640, 640)) == []
    heads = outputs(); heads[1][0, :, 20, 20] = [.7, .6]
    heads[4][0, 1, 10, 10] = .9
    result = decode(heads, ['a', 'b'], (1, 1, 0, 0), (640, 640))
    assert len(result) == 2
    with pytest.raises(ValueError):
        decode(heads[:2], ['a', 'b'], (1, 1, 0, 0), (640, 640))
    assert nms(np.array([[0, 0, 10, 10], [0, 0, 10, 10]], dtype=float), np.array([.8, .9]), .5) == [1]


def test_latest_slot_drops_waiting_frames_and_preserves_final_frame():
    frames = LatestFrames()
    for i in range(5):frames.put(i)
    frames.finish()
    assert frames.received == 5 and frames.dropped == 4
    seq, _, value = frames.take()
    assert seq == 5 and value == 4
    assert frames.take() is None


def test_reader_error_and_complete_frame_assembly():
    frames = LatestFrames(); frames.finish('decoder error')
    with pytest.raises(RuntimeError, match='decoder error'):frames.take()
    assert read_exact(io.BytesIO(b'abcdef'), 6) == b'abcdef'
    assert read_exact(io.BytesIO(), 6) is None
    with pytest.raises(RuntimeError, match='不完整'):read_exact(io.BytesIO(b'abc'), 6)


def test_engine_stale_state_does_not_show_old_counts(tmp_path):
    engine = Engine(Store(tmp_path / 'data'))
    engine.folder = tmp_path / 'run';engine.folder.mkdir()
    atomic_json(engine.folder / 'status.json', {'state': 'running', 'preview_updated_at': time.time() - 10,
        'processing_fps': 20, 'current_counts': {'car': 3}, 'frame_id': 10})
    status = engine.status()
    assert status['stale'] and status['processing_fps'] == 0 and status['current_counts'] is None
    assert not status['inference_connected']


def test_record_snapshot_and_validation_are_real_persistent_entries(tmp_path):
    store = Store(tmp_path)
    jpeg = io.BytesIO();Image.new('RGB', (20, 20)).save(jpeg, 'JPEG')
    store.add_detection({'at': time.time(), 'model_id': None, 'source': 'TEST FIXTURE',
        'counts': {'car': 2}, 'objects': 2, 'inference_ms': 10}, jpeg.getvalue())
    row = store.records()['items'][0]
    assert row['objects'] == 2 and (store.root / 'snapshots' / row['snapshot']).read_bytes() == jpeg.getvalue()
    assert store.statistics()['samples'] == 1


def test_busy_parameters_guard_and_start_failure_does_not_modify_settings(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from uav_app.app import create_app
    app = create_app(tmp_path / 'data');engine = app.state.engine
    client = TestClient(app, headers={'Authorization': 'Bearer ' + (tmp_path / 'data/admin-token.txt').read_text().strip()})
    settings = client.get('/api/settings').json()
    monkeypatch.setattr(engine, 'status', lambda: {'worker_pid': 123})
    assert client.put('/api/settings', json=dict(settings, confidence=.5)).status_code == 409
    assert app.state.store.settings().confidence == .25


def test_camera_ownership_is_checked_before_open(tmp_path, monkeypatch):
    from uav_app import inference_io
    from uav_app.schema import Settings
    monkeypatch.setattr(inference_io, 'locate_ffmpeg', lambda: '/bin/ffmpeg')
    camera = tmp_path / 'video44';camera.touch()
    settings = Settings(source_kind='imx415', source_uri='/dev/video44')
    monkeypatch.setattr(type(camera), 'exists', lambda self: True)
    monkeypatch.setattr(inference_io.os, 'access', lambda *_: True)
    monkeypatch.setattr(inference_io, 'camera_owners', lambda _: [{'pid': 55, 'name': 'other-app'}])
    with pytest.raises(ValueError, match='other-app'):source_spec(Store(tmp_path / 'data'), settings)


def test_disk_reserve_stops_records_without_corrupting_previous(tmp_path, monkeypatch):
    from uav_app import store as module
    store = Store(tmp_path)
    class LowDisk:
        free = 100
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: LowDisk())
    with pytest.raises(ValueError, match='实时检测继续'):
        store.add_detection({'at': 1}, b'jpeg')
    assert store.records()['total'] == 0
    assert not list((tmp_path / 'snapshots').iterdir())


def test_ctypes_structs_match_official_arm64_abi():
    import ctypes
    from uav_app.rknn_backend import Attr, Input, Output
    assert ctypes.sizeof(Attr) == 376
    assert ctypes.sizeof(Input) == 32
    assert ctypes.sizeof(Output) == 24


def test_supervisor_turns_native_crash_into_visible_error(tmp_path):
    engine = Engine(Store(tmp_path / 'data'));engine.folder = tmp_path / 'run';engine.folder.mkdir()
    class DeadProcess:
        returncode = -11
        def poll(self):return self.returncode
    engine.process = DeadProcess()
    atomic_json(engine.folder / 'status.json', {'state': 'starting'})
    state = engine.status()
    assert state['state'] == 'error' and '-11' in state['error']
    assert not state['inference_connected']
    assert state['current_counts'] is None


def test_frame_api_private_missing_and_snapshot_blob(tmp_path):
    from fastapi.testclient import TestClient
    from uav_app.app import create_app
    app = create_app(tmp_path / 'data');client = TestClient(app)
    assert client.get('/api/inference/frame').status_code == 401
    client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'data/admin-token.txt').read_text().strip()
    assert client.get('/api/inference/frame').status_code == 204
    app.state.engine.folder = tmp_path / 'run';app.state.engine.folder.mkdir()
    jpeg = io.BytesIO();Image.new('RGB', (4, 4)).save(jpeg, 'JPEG')
    (app.state.engine.folder / 'frame.jpg').write_bytes(jpeg.getvalue())
    result = client.get('/api/inference/frame')
    assert result.headers['content-type'] == 'image/jpeg' and result.content == jpeg.getvalue()


def test_opt_in_autostart_and_shutdown_are_supervised(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from uav_app.app import create_app
    app = create_app(tmp_path / 'data')
    store = app.state.store
    store.save_settings(store.settings().model_copy(update={'autostart_inference': True}))
    calls = []
    monkeypatch.setattr(app.state.engine, 'start', lambda: calls.append('start'))
    monkeypatch.setattr(app.state.engine, 'stop', lambda: calls.append('stop'))
    with TestClient(app):
        assert calls == ['start']
    assert calls == ['start', 'stop']


def test_actual_camera_mode_reports_planes_without_claiming_sensor_fps(monkeypatch):
    from uav_app import inference_io as module
    class Result:
        returncode = 0
        stdout = b"Width/Height : 1920/1080\nPixel Format : 'NM12'\nNumber of planes : 2\nBytes per Line : 1920\nSize Image : 2073600\nBytes per Line : 1920\nSize Image : 1036800\n"
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: Result())
    import shutil
    monkeypatch.setattr(shutil, 'which', lambda _: '/bin/v4l2-ctl')
    value = module.actual_camera_format('/dev/video44')
    assert value['planes'] == 2 and value['fourcc'] == 'NM12'
    assert value['strides'] == [1920, 1920] and value['fps'] is None


def test_csv_stream_does_not_hold_a_database_connection_across_yields(tmp_path, monkeypatch):
    """A response iterator can run on arbitrary pool threads after each yield."""
    import uuid
    import asyncio
    from contextlib import contextmanager
    from uav_app.app import create_app
    app = create_app(tmp_path / 'data');store = app.state.store
    with store.connect() as db:
        db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',
            [(uuid.uuid4().hex, float(i), None, 'CSV TEST FIXTURE', '{"car":2}', 2, 10., None) for i in range(501)])
    original = store.connect
    connections = [0]
    @contextmanager
    def observed():
        with original() as db:
            connections[0] += 1
            try:yield db
            finally:connections[0] -= 1
    monkeypatch.setattr(store, 'connect', observed)
    endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', None) == '/api/records.csv')
    response = endpoint(search='')
    async def consume():
        chunks = []
        async for part in response.body_iterator:
            assert connections[0] == 0, 'SQLite connection retained across streaming yield'
            chunks.append(part)
        return ''.join(chunks)
    text = asyncio.run(consume())
    assert text.count('CSV TEST FIXTURE') == 501


def test_frame_identity_and_jpeg_are_published_as_one_packet(tmp_path):
    from fastapi.testclient import TestClient
    from uav_app.app import create_app
    app = create_app(tmp_path / 'data');client = TestClient(app)
    client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'data/admin-token.txt').read_text().strip()
    app.state.engine.folder = tmp_path / 'run';app.state.engine.folder.mkdir()
    output = io.BytesIO();Image.new('RGB', (10, 10)).save(output, 'JPEG');jpeg = output.getvalue()
    (app.state.engine.folder / 'frame.bin').write_bytes((987).to_bytes(8, 'big') + jpeg)
    response = client.get('/api/inference/frame')
    assert response.content == jpeg and response.headers['x-frame-id'] == 'run:987'
    assert client.get('/api/inference/frame?after=run%3A987').status_code == 204
    assert client.get('/api/inference/frame?after=previous-run%3A987').status_code == 200
