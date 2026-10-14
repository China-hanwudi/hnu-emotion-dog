"""Exercise the local application with real models and synthetic test inputs."""
import io
import json
from pathlib import Path
import time
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[3]
BASE = 'http://127.0.0.1:8765'


def main():
    session = requests.Session()
    session.trust_env = False
    image = io.BytesIO()
    Image.new('RGB', (320, 240), (30, 100, 200)).save(image, 'PNG')
    sample = (ROOT / '06_测试素材/sensevoice_zh.wav').read_bytes()
    cases = [('text', {'text': '今天实验失败了，我觉得有些难过。'}, None),
             ('text_and_image', {'text': '今天实验成功了，我很开心。'},
              {'image': ('test-blue.png', image.getvalue(), 'image/png')}),
             ('audio_and_image', {}, {'audio': ('official-zh.wav', sample, 'audio/wav'),
                                      'image': ('test-blue.png', image.getvalue(), 'image/png')})]
    report = {}
    for name, data, files in cases:
        began = time.perf_counter()
        response = session.post(BASE + '/api/turn', data=data, files=files, timeout=240)
        response.raise_for_status()
        result = response.json()
        assert result['reply'].strip()
        assert result['image_used'] == bool(files and 'image' in files)
        assert result['robot_playback'] == 'disabled'
        assert result['audio_url'] and result['tts_error'] is None
        speech = session.get(BASE + result['audio_url'], timeout=30)
        speech.raise_for_status()
        assert speech.content[:4] == b'RIFF' and speech.content[8:12] == b'WAVE'
        if files and 'audio' in files:
            assert result['asr']['speech_detected'] and result['text'].strip()
        report[name] = {key: result[key] for key in
                        ('text', 'emotion', 'confidence', 'reply', 'evidence', 'image_used', 'timings')}
        report[name]['elapsed_seconds'] = round(time.perf_counter() - began, 3)
        print(name + ': passed', flush=True)
    target = ROOT / '05_日志/end-to-end-verification.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
