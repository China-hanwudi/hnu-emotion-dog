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

def test_turn_combines_modalities_and_returns_playable_audio(monkeypatch):
    from PIL import Image
    from app import main as module
    from app.config import AUDIO_DIR
    monkeypatch.setenv('ROBOT_ALLOW_PLAYBACK', 'false')
    seen = []
    transcript = '这次实验失败让我有些难过。'
    monkeypatch.setattr(module.speech, 'transcribe', lambda data: {
        'text': transcript, 'audio_emotion': 'sad', 'speech_detected': True})
    async def generate(text, emotion, image, history):
        seen.append((text, emotion, image, list(history)))
        return {'emotion': 'sad', 'confidence': .8, 'reply': '我在这里听你说。',
                'evidence': '用户自己的表达', 'action': 'none'}
    monkeypatch.setattr(module.dialogue, 'generate', generate)
    audio = io.BytesIO()
    sf.write(audio, np.zeros(1600, dtype=np.float32), 16000, format='WAV')
    def synthesize(text):
        name = 'contract-test.wav'
        (AUDIO_DIR / name).write_bytes(audio.getvalue())
        return name
    monkeypatch.setattr(module.speech, 'synthesize', synthesize)
    image = io.BytesIO()
    Image.new('RGB', (32, 32), 'blue').save(image, 'PNG')
    c = TestClient(app)
    response = c.post('/api/turn', data={'text': '音频应当优先', 'session_id': 'contract-modalities'},
                      files={'audio': ('sample.wav', b'controlled-asr-input', 'audio/wav'),
                             'image': ('sample.png', image.getvalue(), 'image/png')})
    assert response.status_code == 200
    result = response.json()
    assert result['text'] == transcript and result['image_used']
    assert seen[0][:2] == (transcript, 'sad') and seen[0][2]
    assert result['robot_playback'] == 'disabled'
    spoken = c.get(result['audio_url'])
    assert spoken.status_code == 200 and spoken.content == audio.getvalue()
    followup = c.post('/api/turn', data={'text': '谢谢', 'session_id': result['session_id']})
    assert followup.status_code == 200 and not followup.json()['image_used']
    assert seen[1][2] is None and seen[1][3][0]['content'] == transcript
    c.delete('/api/session/contract-modalities')

def test_unrecognized_speech_does_not_invoke_model(monkeypatch):
    from app import main as module
    monkeypatch.setattr(module.speech, 'transcribe', lambda data: {
        'text': '', 'audio_emotion': 'unknown', 'speech_detected': False})
    async def generate(*args):
        raise AssertionError('Empty speech must not reach the model')
    monkeypatch.setattr(module.dialogue, 'generate', generate)
    response = TestClient(app).post('/api/turn', files={'audio': ('silence.wav', b'test', 'audio/wav')})
    assert response.status_code == 422

