"""Authenticated local application and supervised real NPU inference."""
from contextlib import asynccontextmanager
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import time

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__
from .resources import ResourceSampler
from .schema import ModelManifest, Settings
from .store import Store, safe_file
from .engine import Engine
from .source_auth import read_credentials, save_credentials

PROJECT = Path(__file__).resolve().parents[2]


def csv_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


def create_app(data_dir=None, web_dir=None):
    store = Store(data_dir or os.environ.get('UAV_DATA_DIR', str(PROJECT / 'data')))
    token_file = store.root / 'admin-token.txt'
    if not token_file.exists():
        with token_file.open('x', encoding='utf-8') as output:
            output.write(secrets.token_urlsafe(24) + '\n')
        token_file.chmod(0o600)
    secret = token_file.read_text().strip()
    engine = Engine(store)

    @asynccontextmanager
    async def lifespan(app):
        if store.settings().autostart_inference:
            try:
                await run_in_threadpool(engine.start)
            except Exception as error:
                engine.last_state = {'state': 'error', 'error': str(error)}
        try:
            yield
        finally:
            await run_in_threadpool(engine.stop)

    app = FastAPI(title='UAV 本地检测工作台', version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store
    app.state.engine = engine
    sampler = ResourceSampler()

    def authenticated(request):
        bearer = request.headers.get('authorization', '')
        if bearer.startswith('Bearer ') and hmac.compare_digest(bearer[7:].encode('utf-8'), secret.encode()):
            return True
        value = request.cookies.get('uav_session', '')
        try:
            expires, signature = value.split('.')
            expected = hmac.new(secret.encode(), expires.encode(), hashlib.sha256).hexdigest()
            return float(expires) > time.time() and hmac.compare_digest(signature, expected)
        except (ValueError, OverflowError, TypeError):
            return False

    @app.middleware('http')
    async def gate(request, call_next):
        path = request.url.path
        if path.startswith('/api/') and path not in ('/api/session', '/api/health'):
            if not authenticated(request):
                return JSONResponse({'detail': '请先输入设备访问码'}, status_code=401)
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '拒绝跨站控制请求'}, status_code=403)
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            return JSONResponse({'detail': '请求长度无效'}, status_code=400)
        if length < 0:
            return JSONResponse({'detail': '请求长度无效'}, status_code=400)
        if request.method == 'POST' and path in ('/api/assets', '/api/models', '/api/session') and not length:
            return JSONResponse({'detail': '上传和登录请求必须声明 Content-Length'}, status_code=411)
        if length > 513 * 1024 * 1024:
            return JSONResponse({'detail': '请求超过上传上限'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ValueError)
    async def bad_input(request, error):
        return JSONResponse({'detail': str(error)}, status_code=400)

    @app.get('/api/health')
    def health():
        return {'ok': True, 'version': __version__, 'inference_connected': engine.status()['inference_connected']}

    @app.get('/api/session')
    def session(request: Request):
        return {'authenticated': authenticated(request)}

    @app.post('/api/session')
    async def login(request: Request):
        # This path accepts tiny JSON only, never multipart data.
        if int(request.headers.get('content-length', '0')) > 4096:
            raise HTTPException(413, '登录请求过大')
        payload = await request.json()
        token = payload.get('token', '') if isinstance(payload, dict) else ''
        if not isinstance(token, str) or len(token) > 256 or not hmac.compare_digest(token.encode('utf-8'), secret.encode()):
            raise HTTPException(401, '访问码不正确')
        expires = str(int(time.time()) + 8 * 3600)
        signature = hmac.new(secret.encode(), expires.encode(), hashlib.sha256).hexdigest()
        response = JSONResponse({'authenticated': True})
        response.set_cookie('uav_session', expires + '.' + signature, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=8 * 3600)
        return response

    @app.delete('/api/session')
    def logout():
        response = JSONResponse({'authenticated': False})
        response.delete_cookie('uav_session')
        return response

    @app.get('/api/status')
    def status():
        settings = store.settings()
        value = engine.status()
        names = {'idle': '等待启动检测', 'starting': '正在加载模型与视频源', 'running': 'NPU 实时检测中',
                 'completed': '素材检测完成', 'stopped': '检测已停止', 'error': '检测发生错误'}
        return dict(value, phase=value['state'], phase_label=names.get(value['state'], value['state']),
                    model=store.model(settings.active_model) if settings.active_model else None,
                    resources=sampler.sample(store.root), updated_at=time.time(), version=__version__)

    @app.post('/api/inference/start')
    def start_inference():
        return engine.start()

    @app.post('/api/inference/stop')
    def stop_inference():
        return engine.stop()

    @app.get('/api/inference/frame')
    def current_frame(after: str = Query('', max_length=100)):
        packet = engine.frame_packet()
        if packet is None:
            return Response(status_code=204)
        identifier, jpeg = packet
        if identifier and after == identifier:
            return Response(status_code=204, headers={'X-Frame-Id': identifier})
        return Response(jpeg, media_type='image/jpeg', headers={'X-Frame-Id': identifier})

    @app.get('/api/inference/logs')
    def inference_logs():
        return engine.logs()

    @app.get('/api/settings')
    def settings():
        return store.settings()

    @app.put('/api/settings')
    def update_settings(value: Settings):
        if engine.status()['worker_pid']:
            raise HTTPException(409, '请先停止检测，再保存模型或视频源参数；避免运行参数与页面不一致')
        return store.save_settings(value)

    @app.get('/api/assets')
    def assets():
        return store.assets()

    @app.get('/api/source-credentials')
    def credentials_status():
        value = read_credentials(store.root, store.settings().source_uri)
        return {'configured': bool(value), 'username': value['username'] if value else ''}

    @app.get('/api/sources/cameras')
    def camera_list():
        from .cameras import list_cameras
        return {'items': list_cameras()}

    @app.put('/api/source-credentials')
    async def update_credentials(request: Request):
        if engine.status()['worker_pid']:
            raise HTTPException(409, '请先停止检测，再修改视频源认证')
        raw = await request.body()
        if len(raw) > 4096:
            raise HTTPException(413, '认证请求过大')
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != {'source_uri', 'username', 'password'}:
                raise ValueError()
            if not all(isinstance(x, str) for x in value.values()):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, '认证请求无效')
        save_credentials(store.root, **value)
        return {'configured': True, 'username': value['username']}

    @app.delete('/api/source-credentials')
    def clear_credentials():
        if engine.status()['worker_pid']:
            raise HTTPException(409, '请先停止检测，再清除认证')
        (store.root / 'source-credentials.json').unlink(missing_ok=True)
        return {'configured': False, 'username': ''}

    @app.post('/api/assets', status_code=201)
    async def upload_asset(file: UploadFile = File(...)):
        try:
            return await run_in_threadpool(store.save_upload, file.file, file.filename or 'upload')
        finally:
            await file.close()

    @app.get('/api/assets/{identifier}/file')
    def asset_file(identifier: str):
        asset = store.asset(identifier)
        if not asset:
            raise HTTPException(404, '文件不存在')
        path = safe_file(store.root / 'uploads', asset['filename'])
        if not path.is_file():
            raise HTTPException(404, '文件已缺失')
        return FileResponse(path, filename=asset['name'], content_disposition_type='inline')

    @app.get('/api/models')
    def models():
        return store.models()

    @app.post('/api/models', status_code=201)
    async def upload_model(model: UploadFile = File(...), manifest: UploadFile = File(...)):
        try:
            raw = await manifest.read(65537)
            if len(raw) > 65536:
                raise HTTPException(400, '模型清单过大')
            try:
                value = ModelManifest.model_validate_json(raw)
            except ValueError as error:
                raise HTTPException(400, '模型清单无效: ' + str(error))
            return await run_in_threadpool(store.save_upload, model.file, model.filename or '', manifest=value)
        finally:
            await model.close()
            await manifest.close()

    @app.get('/api/records')
    def records(search: str = Query('', max_length=100), limit: int = Query(50, ge=1, le=200),
                offset: int = Query(0, ge=0)):
        return store.records(search, limit, offset)

    @app.get('/api/records.csv')
    def export_records(search: str = Query('', max_length=100)):
        # Capture a bounded record snapshot before streaming. Starlette may resume
        # a sync iterator on a different worker thread after every yielded chunk;
        # a live SQLite connection/cursor must never cross those yields.
        with store.connect() as db:
            query = '%' + search + '%'
            rows = db.execute('SELECT * FROM records WHERE source LIKE ? OR counts LIKE ? ORDER BY at DESC',
                              (query, query)).fetchall()

        def generate():
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['UTC时间戳', '视频源', '画面目标数', '各类数量', '推理毫秒'])
            yield '\ufeff' + output.getvalue()
            for row in rows:
                output.seek(0)
                output.truncate(0)
                writer.writerow([row['at'], csv_cell(row['source']), row['objects'],
                                 csv_cell(row['counts']), row['inference_ms']])
                yield output.getvalue()
        return StreamingResponse(generate(), media_type='text/csv; charset=utf-8',
                                 headers={'Content-Disposition': 'attachment; filename="uav-records.csv"'})

    @app.get('/api/records/{identifier}/snapshot')
    def snapshot(identifier: str):
        with store.connect() as db:
            row = db.execute('SELECT snapshot FROM records WHERE id=?', (identifier,)).fetchone()
        if not row or not row[0]:
            raise HTTPException(404, '该记录没有截图')
        path = safe_file(store.root / 'snapshots', row[0])
        if not path.is_file():
            raise HTTPException(404, '截图文件不存在')
        return FileResponse(path, filename=identifier + '.jpg')

    @app.get('/api/statistics')
    def statistics():
        return store.statistics()

    frontend = Path(web_dir or PROJECT / 'frontend/dist')
    if (frontend / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=str(frontend / 'assets')), name='static-assets')

    @app.get('/')
    def index():
        if not (frontend / 'index.html').is_file():
            return JSONResponse({'detail': 'React 页面尚未构建，请先执行前端构建步骤'}, status_code=503)
        return FileResponse(frontend / 'index.html')

    return app
