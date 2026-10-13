"""Run just the paired S. Chat web surface, without desktop background tasks."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--port', type=int, default=5084)
    args = parser.parse_args()
    state = Path(args.state_dir).resolve()
    access = json.loads((state / 'access.json').read_text(encoding='utf-8'))
    os.environ['DATA_DIR'] = str(state / 'data')
    os.environ['MIRU_HEADLESS'] = '1'
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    import app
    from mobile_gateway import MobileGateway
    from waitress import serve
    app._is_client_mode = True
    app._client_mode_config = {'user_id':access['user_id'], 'auth_token':access['internal_token'],
                               'setup_complete':True, 'local_only':True}
    # Skip Curator, sensor, pet and all startup model requests.
    app.app.config['MAX_CONTENT_LENGTH'] = 9 * 1024 * 1024
    gateway = MobileGateway(app.app, access['pairing_code'], access['phone_token'], access['internal_token'])
    # Only the authenticated world-import route raises Flask's per-request
    # limit. Normal image uploads retain their existing 8 MB validation.
    serve(gateway, host='127.0.0.1', port=args.port, threads=8,
          max_request_body_size=512 * 1024 * 1024, expose_tracebacks=False)


if __name__ == '__main__':
    main()
