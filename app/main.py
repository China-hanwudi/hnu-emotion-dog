from __future__ import annotations
import asyncio
from collections import OrderedDict
import json
import logging
import os
import time
import uuid
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import PROJECT, MODEL_DIR, LOG_DIR, AUDIO_DIR, flag
from .robot import RobotClient, RobotError
from . import speech, dialogue

log = logging.getLogger('emotion_dog')
log.setLevel(logging.INFO)
log.addHandler(logging.FileHandler(LOG_DIR / 'turns.jsonl', encoding='utf-8'))
app = FastAPI(title='湖大多模态情感机械狗', docs_url='/docs')
robot = RobotClient()
sessions = OrderedDict()
turn_lock = asyncio.Lock()

@app.middleware('http')
async def local_only(request: Request, call_next):
    # Server binds to loopback. Also reject cross-site mutation attempts against it.
    origin = request.headers.get('origin')
    allowed = {f'http://127.0.0.1:{os.getenv("APP_PORT", "8765")}', f'http://localhost:{os.getenv("APP_PORT", "8765")}'}
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in allowed:
        return PlainTextResponse('Cross-site requests are disabled', status_code=403)
    return await call_next(request)

@app.get('/')
async def home(): return FileResponse(PROJECT / 'static' / 'index.html')

@app.get('/api/health')
async def health():
    import httpx
    models = []
    ollama_error = None
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as c:
            r = await c.get(os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434') + '/api/tags')
            r.raise_for_status()
            models = [m['name'] for m in r.json().get('models', [])]
    except Exception as e: ollama_error = type(e).__name__
    return {'asr_ready': (MODEL_DIR / 'sensevoice' / 'model.int8.onnx').exists(), 'vad_ready': (MODEL_DIR / 'silero_vad.onnx').exists(), 'llm_backend': os.getenv('LLM_BACKEND', 'ollama'), 'llm_model': os.getenv('OLLAMA_MODEL', 'qwen3.5:4b'), 'ollama_models': models, 'ollama_error': ollama_error, 'robot_configured': robot.configured, 'robot_actions_enabled': flag('ROBOT_ALLOW_ACTIONS'), 'robot_playback_enabled': flag('ROBOT_ALLOW_PLAYBACK')}

async def limited_upload(upload, limit):
    if upload is None: return None
    data = await upload.read(limit + 1)
    if len(data) > limit: raise HTTPException(413, '上传文件过大')
    return data

@app.post('/api/turn')
async def turn(text: str = Form(''), session_id: str = Form(''), t_end_ms: float | None = Form(None), audio: UploadFile | None = File(None), image: UploadFile | None = File(None)):
    if len(text) > 2000: raise HTTPException(400, '文字最长2000字')
    if session_id and (len(session_id) > 64 or not all(x.isalnum() or x in '-_' for x in session_id)):
        raise HTTPException(400, '会话编号格式不正确')
    audio_data = await limited_upload(audio, 6_000_000)
    image_data = await limited_upload(image, 5_000_000)
    if not text.strip() and not audio_data: raise HTTPException(400, '请说话、上传音频或输入文字')
    if turn_lock.locked(): raise HTTPException(429, '上一轮正在处理，请稍候')
    async with turn_lock:
        start = time.perf_counter()
        try:
            asr = await asyncio.to_thread(speech.transcribe, audio_data) if audio_data else {'text': text.strip(), 'audio_emotion': 'unknown', 'speech_detected': False}
            user_text = asr['text'] or text.strip()
            if not user_text: raise HTTPException(422, '未检测到可识别的人声，请靠近麦克风后重试')
            image_b64 = await asyncio.to_thread(dialogue.normalize_image, image_data)
            sid = session_id or uuid.uuid4().hex
            state = sessions.setdefault(sid, {'history': [], 'last': time.monotonic()})
            sessions.move_to_end(sid)
            while len(sessions) > 50: sessions.popitem(last=False)
            output = await dialogue.generate(user_text, asr['audio_emotion'], image_b64, state['history'])
            llm_end = time.perf_counter()
            state['history'].extend([{'role': 'user', 'content': user_text}, {'role': 'assistant', 'content': output['reply']}])
            state['history'] = state['history'][-8:]
            state['last'] = time.monotonic()
            audio_url = None
            tts_error = None
            try: audio_url = '/audio/' + await asyncio.to_thread(speech.synthesize, output['reply'])
            except Exception as e: tts_error = f'系统语音不可用（{type(e).__name__}），可使用浏览器朗读'
            playback = 'disabled'
            if flag('ROBOT_ALLOW_PLAYBACK'):
                try:
                    await robot.playback(output['reply'])
                    playback = 'submitted'
                except RobotError as e: playback = str(e)
            result = {'session_id': sid, 'turn_id': uuid.uuid4().hex, 'text': user_text, **output, 'asr': asr, 'audio_url': audio_url, 'tts_error': tts_error, 'robot_playback': playback, 'image_used': bool(image_b64), 't_end_ms': t_end_ms, 'timings': {'inference_seconds': round(llm_end - start, 3), 'total_seconds': round(time.perf_counter() - start, 3)}}
            # Timing/status only: do not log credentials, face images, raw audio or dialogue.
            log.info(json.dumps({k: result[k] for k in ('session_id', 'turn_id', 'image_used', 'timings')}, ensure_ascii=False))
            return result
        except HTTPException: raise
        except ValueError as e: raise HTTPException(400, str(e)) from e
        except Exception as e:
            log.info(json.dumps({'error_type': type(e).__name__}))
            raise HTTPException(503, f'处理失败：{type(e).__name__}。请查看环境状态并确认模型服务已启动。') from e

@app.delete('/api/session/{session_id}')
async def reset(session_id: str):
    sessions.pop(session_id, None)
    return {'ok': True}

@app.get('/api/robot/info')
async def robot_info():
    try: return await robot.info()
    except RobotError as e: raise HTTPException(502, str(e)) from e

@app.post('/api/robot/whep')
async def whep(request: Request):
    raw = await request.body()
    if len(raw) > 100_000: raise HTTPException(413, 'SDP 过大')
    try:
        answer = await robot.request('POST', '/platform/open/api/v1/media/whep/get', query={'force': 'true'}, raw=raw.decode('utf-8'), content_type='application/sdp')
        return PlainTextResponse(answer, media_type='application/sdp')
    except (RobotError, UnicodeDecodeError) as e: raise HTTPException(502, str(e)) from e

class SpeakInput(BaseModel):
    text: str = Field(min_length=1, max_length=500)

@app.post('/api/robot/speak')
async def robot_speak(body: SpeakInput):
    if not flag('ROBOT_ALLOW_PLAYBACK'): raise HTTPException(409, '机器狗播报未启用，请在配置中启用后现场测试')
    try: return await robot.playback(body.text)
    except RobotError as e: raise HTTPException(502, str(e)) from e

class ActionInput(BaseModel):
    action: str

@app.post('/api/robot/action')
async def robot_action(body: ActionInput):
    if not flag('ROBOT_ALLOW_ACTIONS'): raise HTTPException(409, '动作控制未启用')
    if body.action not in ('greeting', 'happy', 'fingerHeart'): raise HTTPException(400, '仅开放已列出的轻量动作')
    # Use returned WebSocket URL, never manufacture or expose a token to the browser.
    import websockets
    try:
        url = await robot.signal_url()
        if isinstance(url, dict): url = url.get('url', '')
        from urllib.parse import urlparse
        if urlparse(url).hostname != urlparse(robot.base).hostname: raise RobotError('信令地址主机与配置不一致，请核对')
        async with websockets.connect(url, open_timeout=10) as ws:
            await ws.send(json.dumps({'deviceId': robot.device, 'domain': 'DEVICE_ABILITY', 'event': 'robot_action', 'eventId': uuid.uuid4().hex, 'seq': str(int(time.time() * 1000)), 'body': {'actionType': 'motorSkill', 'actionArguement': body.action}}))
        return {'status': 'submitted', 'action': body.action}
    except Exception as e: raise HTTPException(502, f'动作提交失败：{type(e).__name__}') from e

app.mount('/audio', StaticFiles(directory=str(AUDIO_DIR)), name='audio')
