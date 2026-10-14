"""Bootstrap a fresh local Dify instance and import this project's workflow."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import requests

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parents[1]
BASE = 'http://127.0.0.1:8080'
PRIVATE = ROOT / '02_运行环境' / 'dify-admin.json'


def main(email):
    if ROOT.drive.upper() == 'C:':
        raise SystemExit('请在 E 盘的项目目录运行本地配置')
    session = requests.Session()
    session.trust_env = False
    session.headers.update({'Origin': BASE, 'Referer': BASE + '/apps'})

    def api(method, path, **kwargs):
        response = session.request(method, BASE + '/console/api' + path,
                                   timeout=180, allow_redirects=False, **kwargs)
        if not response.ok:
            # Print neither credentials nor cookie-bearing response bodies.
            try:
                detail = response.json().get('message', '')[:300]
            except ValueError:
                detail = 'non-JSON response'
            raise RuntimeError(f'Dify {path}: HTTP {response.status_code}: {detail}')
        return response.json()

    def save(state):
        PRIVATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    state = json.loads(PRIVATE.read_text('utf-8')) if PRIVATE.exists() else {}
    status = api('GET', '/setup')
    if status['step'] == 'not_started':
        if not state.get('password'):
            state.update(email=email, password='Aa7_' + secrets.token_urlsafe(18), name='机械狗比赛本地管理员')
            save(state)
        api('POST', '/setup', json={k: state[k] for k in ('email', 'password', 'name')} | {'language': 'zh-Hans'})
        print('Local Dify administrator initialized; credentials stored outside Git', flush=True)
    if not state.get('password'):
        raise RuntimeError('Existing Dify administrator has no local credential file; no account was changed')
    login = api('POST', '/login', json={'email': state['email'],
                                       'password': base64.b64encode(state['password'].encode()).decode(),
                                       'remember_me': False})
    if login.get('result') != 'success':
        raise RuntimeError('Dify login failed')
    csrf = session.cookies.get('csrf_token')
    if not csrf:
        raise RuntimeError('Dify CSRF cookie missing')
    session.headers['X-CSRF-Token'] = csrf
    workflow = (PROJECT / 'deploy/empathy-chatflow.yml').read_text('utf-8')
    workflow_hash = hashlib.sha256(workflow.encode()).hexdigest()
    if state.get('workflow_hash') != workflow_hash or not state.get('app_id'):
        payload = {'mode': 'yaml-content', 'yaml_content': workflow}
        if state.get('app_id'):
            payload['app_id'] = state['app_id']
        imported = api('POST', '/apps/imports', json=payload)
        if imported['status'] == 'pending':
            imported = api('POST', '/apps/imports/' + imported['id'] + '/confirm', json={})
        if imported['status'] not in ('completed', 'completed-with-warnings'):
            raise RuntimeError('Dify workflow import did not complete')
        state['app_id'] = imported['app_id']
        save(state)
        api('POST', '/apps/' + state['app_id'] + '/workflows/publish',
            json={'marked_name': '本地部署', 'marked_comment': '本机 Ollama 文本共情流程'})
        state['workflow_hash'] = workflow_hash
        save(state)
        print('Text empathy workflow imported and published locally', flush=True)
    if not state.get('api_key'):
        key = api('POST', '/apps/' + state['app_id'] + '/api-keys', json={})
        state['api_key'] = key['token']
        save(state)
    env = PROJECT / '.env'
    lines = [line for line in env.read_text('utf-8-sig').splitlines()
             if not line.startswith(('DIFY_API_KEY=', 'DIFY_URL='))]
    lines.extend(['DIFY_URL=' + BASE + '/v1', 'DIFY_API_KEY=' + state['api_key']])
    env.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Dify local API key configured; default multimodal backend preserved', flush=True)
    print('Workflow editor: ' + BASE + '/app/' + state['app_id'] + '/workflow', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', required=True)
    main(parser.parse_args().email)
