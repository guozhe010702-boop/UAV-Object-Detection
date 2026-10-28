import hashlib
import io
import json
import uuid

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from uav_app.app import create_app
from uav_app.schema import ModelManifest
from uav_app.store import safe_file


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path / 'data', tmp_path / 'web')
    client = TestClient(app)
    token = (app.state.store.root / 'admin-token.txt').read_text().strip()
    return client, app.state.store, token


def login(setup):
    client, store, token = setup
    assert client.post('/api/session', json={'token': token}).status_code == 200
    return client, store


def manifest(binary):
    outputs = []
    for size in (80, 40, 20):
        outputs.extend({'shape': shape} for shape in ([1, 64, size, size], [1, 2, size, size], [1, 1, size, size]))
    return {'name': 'TEST FIXTURE, NOT A REAL MODEL', 'input_size': [640, 640], 'classes': ['car', 'people'],
            'labels_zh': ['汽车', '人员'], 'output_layout': 'rockchip-yolo11-dfl-9', 'precision': 'fp16',
            'sha256': hashlib.sha256(binary).hexdigest(), 'onnx_sha256': '0' * 64,
            'source': 'unit-test', 'license': 'test-fixture', 'exported_at': '2026-10-28',
            'outputs': outputs, 'preprocessing': {}, 'conversion': {}}


def image():
    output = io.BytesIO()
    Image.new('RGB', (32, 20), 'white').save(output, 'PNG')
    return output.getvalue()


def test_access_and_explicit_inference_boundary(setup):
    client, _, _ = setup
    assert client.get('/api/health').json()['inference_connected'] is False
    assert client.get('/api/status').status_code == 401
    client, _ = login(setup)
    status = client.get('/api/status').json()
    assert status['processing_fps'] is None and status['current_counts'] is None
    assert client.post('/api/inference/start').status_code == 409


def test_login_logout_and_cross_site_control(setup):
    client, _, token = setup
    assert client.post('/api/session', json={'token': 'wrong'}).status_code == 401
    assert client.post('/api/session', json={'token': '错误访问码'}).status_code == 401
    client.post('/api/session', json={'token': token})
    assert client.get('/api/session').json()['authenticated'] is True
    response = client.put('/api/settings', json={}, headers={'Origin': 'http://another-device'})
    assert response.status_code == 403
    client.delete('/api/session')
    assert client.get('/api/status').status_code == 401


def test_settings_persist_without_starting_camera(setup):
    client, store = login(setup)
    settings = client.get('/api/settings').json()
    settings.update(confidence=0.5, source_kind='imx415', source_uri='/dev/video44')
    assert client.put('/api/settings', json=settings).status_code == 200
    assert store.settings().confidence == 0.5
    assert store.settings().autostart_inference is False
    assert client.get('/api/status').json()['inference_connected'] is False


def test_invalid_source_and_unknown_model_are_rejected(setup):
    client, _ = login(setup)
    settings = client.get('/api/settings').json()
    assert client.put('/api/settings', json=dict(settings, active_model='f' * 32)).status_code == 400
    assert client.put('/api/settings', json=dict(settings, source_kind='file', source_uri='../../etc/passwd')).status_code == 422
    assert client.put('/api/settings', json=dict(settings, source_kind='rtsp', source_uri='rtsp://user:password@host/live')).status_code == 422
    assert client.put('/api/settings', json=dict(settings, confidence=1.5)).status_code == 422


def test_image_upload_is_private_and_retrievable(setup):
    client, store = login(setup)
    response = client.post('/api/assets', files={'file': ('scene.png', image(), 'image/png')})
    assert response.status_code == 201
    row = response.json()
    assert row['kind'] == 'image' and row['bytes'] == len(image())
    assert client.get('/api/assets/' + row['id'] + '/file').content == image()
    assert len(client.get('/api/assets').json()) == 1
    assert not list((store.root / 'uploads').glob('*.part'))


def test_corrupt_image_does_not_leave_file(setup):
    client, store = login(setup)
    response = client.post('/api/assets', files={'file': ('bad.jpg', b'not an image', 'image/jpeg')})
    assert response.status_code == 400
    assert not list((store.root / 'uploads').iterdir())


def test_pt_cannot_be_uploaded_for_server_execution(setup):
    client, _ = login(setup)
    response = client.post('/api/assets', files={'file': ('model.pt', b'pickle', 'application/octet-stream')})
    assert response.status_code == 400


def test_model_checksum_contract_and_pending_status(setup):
    client, _ = login(setup)
    binary = b'UNIT TEST ONLY - NOT A VALID RKNN'
    response = client.post('/api/models', files={
        'model': ('model.rknn', binary, 'application/octet-stream'),
        'manifest': ('manifest.json', json.dumps(manifest(binary)), 'application/json'),
    })
    assert response.status_code == 201
    row = response.json()
    assert row['status'] == 'imported_not_npu_validated'
    settings = client.get('/api/settings').json()
    assert client.put('/api/settings', json=dict(settings, active_model=row['id'])).status_code == 200
    assert client.get('/api/status').json()['model']['id'] == row['id']


def test_model_checksum_failure_cleans_files(setup):
    client, store = login(setup)
    response = client.post('/api/models', files={
        'model': ('model.rknn', b'corrupt', 'application/octet-stream'),
        'manifest': ('manifest.json', json.dumps(manifest(b'expected')), 'application/json'),
    })
    assert response.status_code == 400
    assert not list((store.root / 'models').iterdir())


def test_class_capacity_must_match_output_tensors():
    value = manifest(b'x')
    value['classes'].append('others')
    value['labels_zh'].append('其他')
    with pytest.raises(ValueError):
        ModelManifest.model_validate(value)


def test_records_empty_export_and_observation_scope(setup):
    client, store = login(setup)
    assert client.get('/api/records').json()['total'] == 0
    assert client.get('/api/statistics').json()['trend'] == []
    assert 'UTC时间戳' in client.get('/api/records.csv').text
    with store.connect() as db:
        for timestamp in (1, 2):
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, timestamp, None, '=formula', '{"car":2}', 2, 10, None))
    stats = client.get('/api/statistics').json()
    assert stats['samples'] == 2 and stats['class_observations']['car'] == 4
    assert "'=formula" in client.get('/api/records.csv').text
    assert client.get('/api/records?search=car').json()['total'] == 2


def test_file_escape_and_unknown_snapshot_are_rejected(setup, tmp_path):
    client, _ = login(setup)
    with pytest.raises(ValueError):
        safe_file(tmp_path, '../../other.jpg')
    assert client.get('/api/records/' + '0' * 32 + '/snapshot').status_code == 404


def test_upload_size_checked_before_reading_body(setup):
    client, _ = login(setup)
    response = client.post('/api/assets', content=b'x', headers={'Content-Length': str(600 * 1024**2)})
    assert response.status_code == 413


def test_frontend_missing_is_explicit(setup):
    client, _, _ = setup
    assert client.get('/').status_code == 503
