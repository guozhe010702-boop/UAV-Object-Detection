"""Private RTSP credentials, tied to one exact source URI. Never returned in status."""
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urlsplit, urlunsplit


def read_credentials(root, source_uri):
    try:
        value = json.loads((Path(root) / 'source-credentials.json').read_text(encoding='utf-8'))
        if value.get('source_uri') == source_uri:
            return value
    except (OSError, ValueError):
        pass
    return None


def save_credentials(root, source_uri, username, password):
    from .schema import Settings
    Settings(source_kind='rtsp', source_uri=source_uri)
    if not source_uri or not username or len(username) > 128 or not password or len(password) > 512:
        raise ValueError('RTSP 地址、用户名或密码长度无效')
    if any(ord(c) < 32 for c in username + password):
        raise ValueError('用户名或密码不应包含控制字符')
    path = Path(root) / 'source-credentials.json'
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump({'source_uri': source_uri, 'username': username, 'password': password}, output, ensure_ascii=False)
    temporary.replace(path)


def authenticated_uri(root, uri):
    value = read_credentials(root, uri)
    if not value:
        return uri
    parsed = urlsplit(uri)
    authority = quote(value['username'], safe='') + ':' + quote(value['password'], safe='') + '@' + parsed.netloc
    return urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))


def redact(text, credentials=None):
    text = re.sub(r'(rtsps?://)[^\s/]+@', r'\1***@', text)
    if credentials:
        for secret in (credentials.get('password'), quote(credentials.get('password', ''), safe='')):
            if secret:text = text.replace(secret, '***')
    return text


def public_source(source):
    return {k: v for k, v in source.items() if k not in ('args', 'uri', 'binary')}
