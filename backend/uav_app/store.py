"""SQLite metadata and UUID-addressed private files, independent of av_dev."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from .schema import ModelManifest, Settings


def safe_file(folder, filename):
    folder = Path(folder).resolve()
    path = (folder / filename).resolve()
    if path.parent != folder or not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png|mp4|mov|mkv|rknn|json)', filename):
        raise ValueError('文件路径无效')
    return path


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ('uploads', 'models', 'snapshots'):
            (self.root / name).mkdir(exist_ok=True)
        self.database = self.root / 'uav.sqlite3'
        self.upload_lock = threading.Lock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    filename TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY, manifest TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, at REAL NOT NULL, model_id TEXT,
                    source TEXT NOT NULL, counts TEXT NOT NULL, objects INTEGER NOT NULL, inference_ms REAL,
                    snapshot TEXT);
                CREATE INDEX IF NOT EXISTS records_time ON records(at DESC);
                CREATE TABLE IF NOT EXISTS model_validation(id TEXT PRIMARY KEY, at REAL NOT NULL, details TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (Settings().model_dump_json(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.database), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.connect() as db:
            return Settings.model_validate_json(db.execute('SELECT payload FROM settings WHERE id=1').fetchone()[0])

    def save_settings(self, settings):
        if settings.active_model and not self.model(settings.active_model):
            raise ValueError('待用模型不存在')
        if settings.source_kind == 'file' and settings.source_uri and not self.asset(settings.source_uri):
            raise ValueError('媒体文件不存在')
        with self.connect() as db:
            db.execute('UPDATE settings SET payload=? WHERE id=1', (settings.model_dump_json(),))
        return settings

    def assets(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM assets ORDER BY created DESC')]

    def asset(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM assets WHERE id=?', (identifier,)).fetchone()
        return dict(row) if row else None

    def model(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM models WHERE id=?', (identifier,)).fetchone()
            validation = db.execute('SELECT at,details FROM model_validation WHERE id=?', (identifier,)).fetchone()
        return dict(id=row['id'], manifest=json.loads(row['manifest']), created=row['created'],
                    status='npu_execution_verified' if validation else 'imported_not_npu_validated',
                    validation={'at': validation['at'], 'details': json.loads(validation['details'])} if validation else None) if row else None

    def mark_model_validated(self, identifier, details):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO model_validation VALUES(?,?,?)',
                       (identifier, time.time(), json.dumps(details)))

    def add_detection(self, row, jpeg):
        """Reserve space, persist one genuine sampled frame, retain at most 10k records."""
        identifier = uuid.uuid4().hex
        target = safe_file(self.root / 'snapshots', identifier + '.jpg')
        with self.upload_lock:
            if shutil.disk_usage(self.root).free < 1024**3 + len(jpeg):
                raise ValueError('存储不足 1 GiB，已暂停保存记录；实时检测继续')
            try:
                target.write_bytes(jpeg)
                with self.connect() as db:
                    db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)', (identifier, row['at'], row['model_id'],
                        row['source'], json.dumps(row['counts'], ensure_ascii=False), row['objects'], row['inference_ms'], target.name))
                    old = db.execute('SELECT id,snapshot FROM records ORDER BY at DESC LIMIT -1 OFFSET 10000').fetchall()
                    db.executemany('DELETE FROM records WHERE id=?', [(r['id'],) for r in old])
                for entry in old:
                    if entry['snapshot']:
                        safe_file(self.root / 'snapshots', entry['snapshot']).unlink(missing_ok=True)
            except BaseException:
                target.unlink(missing_ok=True)
                raise

    def models(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM models ORDER BY created DESC')]
        return [self.model(identifier) for identifier in ids]

    def save_upload(self, stream, filename, *, manifest=None):
        suffix = Path(filename.replace('\\', '/')).suffix.lower()
        is_model = manifest is not None
        allowed = ('.rknn',) if is_model else ('.jpg', '.jpeg', '.png', '.mp4', '.mov', '.mkv')
        if suffix not in allowed:
            raise ValueError('不支持该文件类型')
        if suffix == '.jpeg':
            suffix = '.jpg'
        if manifest is not None:
            manifest = ModelManifest.model_validate(manifest)
        identifier = uuid.uuid4().hex
        folder = self.root / ('models' if is_model else 'uploads')
        target = safe_file(folder, identifier + suffix)
        temporary = target.with_suffix('.part')
        digest, length = hashlib.sha256(), 0
        # Serialize disk reservations so simultaneous uploads cannot consume the same free space.
        with self.upload_lock:
            try:
                with temporary.open('xb') as output:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        length += len(chunk)
                        if length > 512 * 1024 * 1024:
                            raise ValueError('单个文件不能超过 512 MiB')
                        if shutil.disk_usage(folder).free < 1024**3 + len(chunk):
                            raise ValueError('剩余空间不足，至少保留 1 GiB')
                        output.write(chunk)
                        digest.update(chunk)
                if not length:
                    raise ValueError('文件为空')
                if manifest and digest.hexdigest() != manifest.sha256:
                    raise ValueError('RKNN 文件 SHA-256 与模型清单不一致')
                if not is_model and suffix in ('.jpg', '.png'):
                    from PIL import Image
                    try:
                        with Image.open(temporary) as image:
                            if image.width * image.height > 40_000_000:
                                raise ValueError('图片尺寸过大')
                            image.verify()
                    except (OSError, Image.DecompressionBombError) as error:
                        raise ValueError('无法读取该图片') from error
                temporary.replace(target)
                clean_name = ''.join(c for c in filename.replace('\\', '/').split('/')[-1] if ord(c) >= 32)[:150]
                with self.connect() as db:
                    if manifest:
                        db.execute('INSERT INTO models VALUES(?,?,?)', (identifier, manifest.model_dump_json(), time.time()))
                    else:
                        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?)',
                                   (identifier, clean_name, 'image' if suffix in ('.jpg', '.png') else 'video',
                                    target.name, length, digest.hexdigest(), time.time()))
                return self.model(identifier) if manifest else self.asset(identifier)
            except BaseException:
                temporary.unlink(missing_ok=True)
                target.unlink(missing_ok=True)
                raise

    def records(self, search='', limit=50, offset=0):
        query = '%' + search + '%'
        with self.connect() as db:
            where = ' WHERE source LIKE ? OR counts LIKE ?'
            total = db.execute('SELECT COUNT(*) FROM records' + where, (query, query)).fetchone()[0]
            rows = db.execute('SELECT * FROM records' + where + ' ORDER BY at DESC LIMIT ? OFFSET ?',
                              (query, query, limit, offset)).fetchall()
        return {'total': total, 'items': [dict(dict(row), counts=json.loads(row['counts'])) for row in rows]}

    def statistics(self):
        with self.connect() as db:
            total = db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
            rows = db.execute('SELECT at,counts,objects FROM records ORDER BY at DESC LIMIT 600').fetchall()
        counts = {}
        for row in rows:
            for label, value in json.loads(row['counts']).items():
                counts[label] = counts.get(label, 0) + value
        return {'samples': total, 'window_samples': len(rows), 'class_observations': counts,
                'trend': [{'at': r['at'], 'objects': r['objects']} for r in reversed(rows)],
                'counting_scope': '每次画面采样的目标数累计，非跨帧去重或车流量'}
