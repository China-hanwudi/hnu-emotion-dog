from __future__ import annotations
from functools import lru_cache
import io
import re
import threading
import uuid
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from .config import MODEL_DIR, AUDIO_DIR

ASR_LOCK = threading.Lock()

@lru_cache(maxsize=1)
def recognizer():
    import sherpa_onnx
    folder = MODEL_DIR / 'sensevoice'
    if not (folder / 'model.int8.onnx').exists(): raise RuntimeError('中文语音模型尚未下载完成')
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(folder / 'model.int8.onnx'), tokens=str(folder / 'tokens.txt'), num_threads=4, use_itn=True, debug=False, provider='cpu')

def read_audio(data):
    try: samples, rate = sf.read(io.BytesIO(data), dtype='float32', always_2d=True)
    except Exception as e: raise ValueError('请提供 WAV、FLAC 或 OGG 音频') from e
    if rate < 8000 or rate > 96000: raise ValueError('音频采样率不支持')
    if len(samples) / rate > 30: raise ValueError('单轮音频最长30秒')
    if len(samples) / rate < .2: raise ValueError('音频过短')
    mono = np.clip(samples.mean(axis=1), -1, 1)
    if rate != 16000:
        import math
        gcd = math.gcd(rate, 16000)
        mono = resample_poly(mono, 16000 // gcd, rate // gcd).astype(np.float32)
    return np.ascontiguousarray(mono)

def speech_segments(samples):
    import sherpa_onnx
    path = MODEL_DIR / 'silero_vad.onnx'
    if not path.exists(): raise RuntimeError('VAD 模型尚未下载完成')
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(path)
    config.silero_vad.threshold = .5
    config.silero_vad.min_silence_duration = .5
    config.silero_vad.min_speech_duration = .2
    config.sample_rate = 16000
    detector = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=35)
    window = config.silero_vad.window_size
    chunks = []
    for i in range(0, len(samples), window):
        frame = samples[i:i + window]
        if len(frame) < window: frame = np.pad(frame, (0, window - len(frame)))
        detector.accept_waveform(frame)
        while not detector.empty():
            segment = detector.front
            chunks.append((segment.start, np.asarray(segment.samples).copy()))
            detector.pop()
    detector.flush()
    while not detector.empty():
        segment = detector.front
        chunks.append((segment.start, np.asarray(segment.samples).copy()))
        detector.pop()
    return chunks

def transcribe(data):
    samples = read_audio(data)
    chunks = speech_segments(samples)
    if not chunks: return {'text': '', 'audio_emotion': 'unknown', 'speech_detected': False}
    with ASR_LOCK:
        model = recognizer()
        streams = []
        for _, audio in chunks:
            stream = model.create_stream()
            stream.accept_waveform(16000, audio)
            streams.append(stream)
        model.decode_streams(streams)
        results = [s.result for s in streams]
        raw = ' '.join(r.text for r in results)
        emotion = next((str(getattr(r, 'emotion', '')).lower() for r in results if getattr(r, 'emotion', '')), 'unknown')
        emotion = emotion.replace('<|', '').replace('|>', '')
        tags = re.findall(r'<\|([^|]+)\|>', raw)
        for tag in tags:
            if tag.lower() in ('happy', 'sad', 'angry', 'neutral', 'fearful', 'disgusted', 'surprised'):
                emotion = tag.lower()
        text = re.sub(r'<\|[^|]+\|>', '', raw).strip()
    return {'text': text, 'audio_emotion': emotion, 'speech_detected': bool(text), 'speech_seconds': round(sum(len(c) for _, c in chunks) / 16000, 3), 'speech_end_seconds': round((chunks[-1][0] + len(chunks[-1][1])) / 16000, 3)}

def synthesize(text):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    stream = None
    try:
        voice = win32com.client.Dispatch('SAPI.SpVoice')
        for token in voice.GetVoices():
            if any(name in token.GetDescription().lower() for name in ('huihui', 'kangkang', 'yaoyao', 'chinese', 'zh-cn')):
                voice.Voice = token
                break
        target = AUDIO_DIR / (uuid.uuid4().hex + '.wav')
        stream = win32com.client.Dispatch('SAPI.SpFileStream')
        stream.Open(str(target), 3)
        voice.AudioOutputStream = stream
        voice.Rate = 0
        voice.Speak(text[:500])
        stream.Close()
        stream = None
        if target.stat().st_size <= 44: raise RuntimeError('系统语音未生成有效音频')
        return target.name
    finally:
        if stream is not None: stream.Close()
        pythoncom.CoUninitialize()

