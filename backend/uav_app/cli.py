import argparse
import json
import os
from pathlib import Path

from .app import PROJECT, create_app


def main():
    p = argparse.ArgumentParser(description='UAV 本地网页与 RKNN NPU 检测服务')
    p.add_argument('action', choices=('serve', 'token', 'import-model', 'start', 'stop', 'status', 'logs'))
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8088)
    p.add_argument('--bundle', type=Path)
    args = p.parse_args()
    if args.action in ('start', 'stop', 'status', 'logs'):
        import urllib.request
        root = Path(os.environ.get('UAV_DATA_DIR', str(PROJECT / 'data')))
        token = (root / 'admin-token.txt').read_text().strip()
        routes = {'start': 'inference/start', 'stop': 'inference/stop', 'status': 'status', 'logs': 'inference/logs'}
        data = b'{}' if args.action in ('start', 'stop') else None
        request = urllib.request.Request('http://127.0.0.1:%s/api/%s' % (args.port, routes[args.action]), data=data,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            print(json.dumps(json.load(urllib.request.urlopen(request, timeout=30)), ensure_ascii=False, indent=2))
        except urllib.error.HTTPError as error:
            raise SystemExit(error.read().decode('utf-8', errors='replace'))
        return
    app = create_app()
    store = app.state.store
    if args.action == 'token':
        print((store.root / 'admin-token.txt').read_text().strip())
    elif args.action == 'import-model':
        if not args.bundle:
            p.error('--bundle is required')
        manifest = json.loads((args.bundle / 'manifest.json').read_text(encoding='utf-8'))
        with (args.bundle / 'model.rknn').open('rb') as source:
            row = store.save_upload(source, 'model.rknn', manifest=manifest)
        print(json.dumps({'imported': row['id'], 'status': row['status']}))
    else:
        import uvicorn
        # A single web process supervises its isolated native RKNN worker.
        uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == '__main__':
    main()
