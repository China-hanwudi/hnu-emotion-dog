import base64
import hashlib
import hmac
import io
import json
from urllib.parse import quote
import numpy as np
import pytest
import soundfile as sf
import httpx
from fastapi.testclient import TestClient
from app.robot import canonical_signature, RobotClient, RobotError
from app.dialogue import parse_result, normalize_image
from app.speech import read_audio
from app.main import app

def test_signature_escaping_and_order():
    params = {'tenantCode': '中文 空格', 'nonce': 'a+b', 'timestamp': '1'}
    query = 'nonce=a%2Bb&tenantCode=%E4%B8%AD%E6%96%87%20%E7%A9%BA%E6%A0%BC&timestamp=1'
    expected = base64.b64encode(hmac.new(b'secret&', ('GET&%2F&' + quote(query, safe='-_.~')).encode(), hashlib.sha1).digest()).decode()
    assert canonical_signature('GET', params, 'secret') == expected
    assert canonical_signature('GET', dict(reversed(list(params.items()))), 'secret') == expected

def test_json_is_not_trusted_for_actions():
    r = parse_result(json.dumps({'reply':'我在这里听你说。','emotion':'sad','confidence':.7,'action':'jumpForward'}))
    assert r['action'] == 'none'
    with pytest.raises(ValueError): parse_result('{"reply":"a","confidence":2}')

def test_audio_resampling_and_limits():
    b=io.BytesIO(); sf.write(b,np.zeros(48000,dtype=np.float32),48000,format='WAV')
    assert read_audio(b.getvalue()).shape == (16000,)
    b=io.BytesIO(); sf.write(b,np.zeros(16000*31,dtype=np.float32),16000,format='WAV')
    with pytest.raises(ValueError): read_audio(b.getvalue())

def test_cross_site_and_actions_disabled(monkeypatch):
    monkeypatch.setenv('ROBOT_ALLOW_ACTIONS','false')
    c=TestClient(app)
    assert c.post('/api/robot/action',json={'action':'greeting'}).status_code == 409
    assert c.post('/api/turn',data={'text':'hello'},headers={'Origin':'https://other.example'}).status_code == 403
    assert c.post('/api/turn',data={'text':'a'*2001}).status_code == 400

@pytest.mark.asyncio
async def test_signed_client_never_forwards_credentials_on_redirect(monkeypatch):
    import app.robot as module
    real_client=httpx.AsyncClient
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(302,headers={'location':'https://other.example'})
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw: real_client(transport=httpx.MockTransport(handler),**kw))
    client=RobotClient();client.base='https://robot.example';client.device='d';client.tenant='t';client.key='k';client.secret='s'
    with pytest.raises(RobotError): await client.info()
    assert len(seen)==1
    assert seen[0].headers['VSS-Device-Id']=='d'

