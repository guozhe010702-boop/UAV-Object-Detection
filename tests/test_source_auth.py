import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from uav_app.app import create_app
from uav_app.source_auth import authenticated_uri, public_source, read_credentials, redact, save_credentials


def test_credentials_are_bound_to_exact_source_and_encoded(tmp_path):
    uri = 'rtsp://127.0.0.1:8556/live'
    save_credentials(tmp_path, uri, 'user@name', 'p:/@?#')
    assert authenticated_uri(tmp_path, uri) == 'rtsp://user%40name:p%3A%2F%40%3F%23@127.0.0.1:8556/live'
    assert authenticated_uri(tmp_path, uri + '2') == uri + '2'
    assert read_credentials(tmp_path, uri)['password'] == 'p:/@?#'
    assert public_source({'name': uri, 'args': ['secret'], 'uri': 'secret', 'width': 1280}) == {'name': uri, 'width': 1280}


def test_log_redaction_removes_authority_and_raw_password():
    text = 'Input rtsp://reader:p%3A%2F%40%3F%23@127.0.0.1/live Password p:/@?#'
    result = redact(text, {'password': 'p:/@?#'})
    assert 'p%3A' not in result and 'p:/@?#' not in result and 'reader:' not in result


def test_auth_api_never_returns_password_and_requires_stop(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'data');client = TestClient(app)
    assert client.get('/api/source-credentials').status_code == 401
    client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'data/admin-token.txt').read_text().strip()
    settings = client.get('/api/settings').json()
    settings.update(source_kind='rtsp', source_uri='rtsp://camera/live')
    assert client.put('/api/settings', json=settings).status_code == 200
    credentials = {'source_uri': settings['source_uri'], 'username': 'reader', 'password': 'TOP_SECRET'}
    response = client.put('/api/source-credentials', json=credentials)
    assert response.status_code == 200 and 'TOP_SECRET' not in response.text
    assert client.get('/api/source-credentials').json() == {'configured': True, 'username': 'reader'}
    assert 'TOP_SECRET' not in client.get('/api/status').text
    monkeypatch.setattr(app.state.engine, 'status', lambda: {'worker_pid': 100})
    assert client.delete('/api/source-credentials').status_code == 409
    assert client.put('/api/source-credentials', json=credentials).status_code == 409
    monkeypatch.setattr(app.state.engine, 'status', lambda: {'worker_pid': None})
    assert client.delete('/api/source-credentials').json()['configured'] is False


def test_auth_validation_does_not_echo_secret(tmp_path):
    app = create_app(tmp_path / 'data');client = TestClient(app)
    client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'data/admin-token.txt').read_text().strip()
    response = client.put('/api/source-credentials', json={'password': 'SECRET_ONLY'})
    assert response.status_code == 400 and 'SECRET_ONLY' not in response.text
    with pytest.raises(ValueError):save_credentials(tmp_path / 'data', 'rtsp://user:pass@camera/live', 'a', 'b')
