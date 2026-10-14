"""Download upstream assets into E: and retain a source/hash manifest."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile
import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '04_下载缓存'
MODELS = ROOT / '03_模型'
RUNTIME = ROOT / '02_运行环境'
MANIFEST = CACHE / 'downloads.json'

def download(url: str, target: Path, minimum: int = 1):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size >= minimum:
        print(f'Already downloaded: {target.name}', flush=True)
        return target
    partial = target.with_suffix(target.suffix + '.part')
    for attempt in range(6):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            with requests.get(url, headers={'Range': f'bytes={offset}-'} if offset else {}, stream=True, timeout=(30, 90)) as r:
                r.raise_for_status()
                append = offset > 0 and r.status_code == 206
                if not append: offset = 0
                total = int(r.headers.get('content-length', 0)) + offset
                last = time.monotonic()
                with partial.open('ab' if append else 'wb') as f:
                    for chunk in r.iter_content(1024 * 1024):
                        f.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last > 15:
                            print(f'{target.name}: {offset // 1048576}/{total // 1048576} MiB', flush=True)
                            last = time.monotonic()
                if partial.stat().st_size < minimum: raise ValueError('Downloaded file too small')
                if total and partial.stat().st_size != total: raise ValueError('Incomplete download')
                partial.replace(target)
            digest = hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()
            old = json.loads(MANIFEST.read_text('utf-8')) if MANIFEST.exists() else {}
            old[target.name] = {'url': url, 'bytes': target.stat().st_size, 'sha256': digest}
            MANIFEST.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'Download complete: {target.name}', flush=True)
            return target
        except (requests.RequestException, ValueError, OSError) as e:
            print(f'Retrying {target.name}: {type(e).__name__} ({attempt + 1}/6)', flush=True)
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f'Cannot download {target.name}')

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('component', choices=['speech', 'ollama'])
    args = p.parse_args()
    if args.component == 'speech':
        base = 'https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/'
        download(base + 'model.int8.onnx', MODELS / 'sensevoice' / 'model.int8.onnx', 100_000_000)
        download(base + 'tokens.txt', MODELS / 'sensevoice' / 'tokens.txt', 1000)
        download(base + 'test_wavs/zh.wav', ROOT / '06_测试素材' / 'sensevoice_zh.wav', 1000)
        download('https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx', MODELS / 'silero_vad.onnx', 100_000)
    else:
        asset = download('https://github.com/ollama/ollama/releases/download/v0.40.4/ollama-windows-amd64.zip', CACHE / 'ollama-windows-amd64-v0.40.4.zip', 10_000_000)
        dest = RUNTIME / 'Ollama'
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(asset) as z:
            for entry in z.infolist():
                final = (dest / entry.filename).resolve()
                if not final.is_relative_to(dest.resolve()): raise ValueError('Unsafe archive path')
            z.extractall(dest)
        print(f'Ollama extracted to {dest}', flush=True)

if __name__ == '__main__': main()

