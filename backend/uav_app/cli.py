import argparse
import json
import os
from pathlib import Path

from .app import PROJECT, create_app


def main():
    p = argparse.ArgumentParser(description='UAV 本地网页应用；本阶段不启动检测')
    p.add_argument('action', choices=('serve', 'token', 'import-model'))
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8088)
    p.add_argument('--bundle', type=Path)
    args = p.parse_args()
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
        # One process owns SQLite/settings; inference workers will be added in stage 02.
        uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == '__main__':
    main()
