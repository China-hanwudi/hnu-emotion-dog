"""Official VSS adapter. Secret stays local; signing algorithm is configurable."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import quote
import httpx

class RobotError(RuntimeError): pass

def canonical_signature(method, params, secret, algorithm='sha1'):
    if algorithm not in ('sha1', 'sha256'): raise ValueError('Unsupported HMAC algorithm')
    def enc(value): return quote(str(value), safe='-_.~')
    query = '&'.join(f'{enc(k)}={enc(v)}' for k, v in sorted(params.items()) if k != 'sign')
    # Appendix 1: method, encoded slash, encoded sorted query.
    to_sign = f'{method.upper()}&%2F&{enc(query)}'
    return base64.b64encode(hmac.new((secret + '&').encode(), to_sign.encode(), getattr(hashlib, algorithm)).digest()).decode()

class RobotClient:
    def __init__(self):
        self.base = os.getenv('ROBOT_BASE_URL', '').rstrip('/')
        self.device = os.getenv('ROBOT_DEVICE_ID', '')
        self.tenant = os.getenv('ROBOT_TENANT_CODE', '')
        self.key = os.getenv('ROBOT_ACCESS_KEY', '')
        self.secret = os.getenv('ROBOT_ACCESS_SECRET', '')

    @property
    def configured(self): return bool(self.base and self.device and self.tenant and self.key and self.secret)

    async def request(self, method, path, query=None, payload=None, raw=None, content_type=None):
        if not self.configured: raise RobotError('机器狗凭证未配置')
        if not path.startswith('/platform/open/api/v1/'): raise RobotError('不支持的接口路径')
        query = query or {}
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')) if payload is not None else raw
        values = {'tenantCode': self.tenant, 'nonce': secrets.token_hex(8), 'timestamp': str(int(time.time() * 1000)), 'accessKey': self.key, 'deviceId': self.device}
        values.update({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in query.items()})
        if body is not None and os.getenv('ROBOT_BODY_SIGN_MODE', 'content') == 'content': values['content'] = body
        headers = {'VSS-Tenant-Code': self.tenant, 'VSS-Nonce': values['nonce'], 'VSS-Timestamp': values['timestamp'], 'VSS-Access-Key': self.key, 'VSS-Device-Id': self.device}
        headers['VSS-Sign'] = canonical_signature(method, values, self.secret, os.getenv('ROBOT_HMAC_ALGORITHM', 'sha1'))
        if body is not None: headers['Content-Type'] = content_type or 'application/json'
        if content_type == 'application/sdp': headers['Accept'] = 'application/sdp'
        try:
            # Credentials belong to this host. Never follow a redirect with signed headers.
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as c:
                r = await c.request(method, self.base + path, params=query, content=body.encode('utf-8') if body is not None else None, headers=headers)
            if r.is_redirect: raise RobotError('平台返回重定向，请核对实际接口地址')
            if r.status_code >= 400: raise RobotError(f'平台 HTTP {r.status_code}；请核对地址、激活状态和鉴权脚本')
            if content_type == 'application/sdp': return r.text
            data = r.json()
            if data.get('code', 0) != 0: raise RobotError(f"平台业务错误 {data.get('code')}：{str(data.get('msg', ''))[:150]}")
            return data
        except (httpx.HTTPError, ValueError) as e:
            raise RobotError(f'平台请求失败：{type(e).__name__}') from e

    async def info(self): return await self.request('GET', '/platform/open/api/v1/device-info/info')
    async def playback(self, text):
        return await self.request('POST', '/platform/open/api/v1/llm/voice/play', payload={'text': text[:500], 'type': 2, 'playStrategy': '1'})
    async def signal_url(self):
        result = await self.request('GET', '/platform/open/api/v1/realtime-control/websocket/url', query={'clientId': self.device})
        return result['data']

