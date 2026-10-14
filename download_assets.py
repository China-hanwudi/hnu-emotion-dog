"""Download upstream assets into E: and retain a source/hash manifest."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile
import requests
from concurrent.futures import ThreadPoolExecutor
import subprocess
import urllib.request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

def download_local_model():
    """Fetch the official registry artifacts with normal TLS verification.

    Keeps the standard Ollama manifest/blob layout and verifies every blob
    against its registry SHA256 before installing the manifest.
    """
    registry = 'https://registry.ollama.ai/v2/library/qwen3.5'
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=6, backoff_factor=1)))
    response = session.get(registry + '/manifests/4b', timeout=30)
    response.raise_for_status()
    manifest = response.json()
    model_root = MODELS / 'ollama'
    blob_root = model_root / 'blobs'
    blob_root.mkdir(parents=True, exist_ok=True)

    def fetch_blob(layer):
        digest = layer['digest']
        if not digest.startswith('sha256:') or len(digest) != 71:
            raise ValueError('Unsupported registry digest')
        int(digest[7:], 16)
        target = blob_root / digest.replace(':', '-')
        expected_size = int(layer['size'])
        partial = target.with_suffix('.download')
        if target.exists():
            with target.open('rb') as f:
                actual = hashlib.file_digest(f, 'sha256').hexdigest()
            if target.stat().st_size != expected_size or actual != digest[7:]:
                quarantine = CACHE / 'damaged-model-files'
                quarantine.mkdir(exist_ok=True)
                target.replace(quarantine / (target.name + '.' + str(time.time_ns())))
                print('Damaged model blob preserved for diagnosis: ' + digest[7:19], flush=True)
        aria_candidates = list((RUNTIME / 'aria2').glob('**/aria2c.exe'))
        if expected_size > 50_000_000 and not target.exists() and aria_candidates:
            command = [str(aria_candidates[0]), '--no-conf', '--continue=true',
                '--max-connection-per-server=6', '--split=6', '--min-split-size=8M',
                '--max-tries=20', '--retry-wait=5', '--timeout=90',
                '--file-allocation=none', '--check-integrity=true',
                '--checksum=sha-256=' + digest[7:], '--summary-interval=30',
                '--show-console-readout=false', '--console-log-level=warn',
                '--download-result=hide', '--dir=' + str(blob_root),
                '--out=' + partial.name]
            proxy = urllib.request.getproxies().get('https')
            if proxy: command.append('--all-proxy=' + proxy)
            command.append(registry + '/blobs/' + digest)
            log_path = ROOT / '05_日志' / ('model-download-' + digest[7:19] + '.log')
            print('Segmented model download started: ' + digest[7:19], flush=True)
            with log_path.open('w', encoding='utf-8') as output:
                subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)
            with partial.open('r+b') as f:
                f.flush()
                os.fsync(f.fileno())
            with partial.open('rb') as f:
                actual = hashlib.file_digest(f, 'sha256').hexdigest()
            if partial.stat().st_size != expected_size or actual != digest[7:]:
                raise ValueError('Segmented download checksum mismatch')
            partial.replace(target)
        for attempt in range(16):
            try:
                if not target.exists():
                    offset = partial.stat().st_size if partial.exists() else 0
                    headers = {'Range': f'bytes={offset}-'} if offset else {}
                    with session.get(registry + '/blobs/' + digest,
                                      headers=headers, stream=True,
                                      timeout=(30, 90)) as r:
                        r.raise_for_status()
                        append = offset > 0 and r.status_code == 206
                        if not append: offset = 0
                        last = time.monotonic()
                        with partial.open('ab' if append else 'wb') as f:
                            for chunk in r.iter_content(1024 * 1024):
                                f.write(chunk)
                                offset += len(chunk)
                                if time.monotonic() - last > 15:
                                    print(f'{digest[7:19]}: {offset // 1048576}/{expected_size // 1048576} MiB', flush=True)
                                    last = time.monotonic()
                            f.flush()
                            os.fsync(f.fileno())
                    if partial.stat().st_size != expected_size:
                        raise ValueError('Incomplete model blob')
                    with partial.open('rb') as f:
                        actual = hashlib.file_digest(f, 'sha256').hexdigest()
                    if actual != digest[7:]:
                        partial.unlink()
                        raise ValueError('Model SHA256 mismatch')
                    partial.replace(target)
                else:
                    with target.open('rb') as f:
                        actual = hashlib.file_digest(f, 'sha256').hexdigest()
                    if target.stat().st_size != expected_size or actual != digest[7:]:
                        raise ValueError('Existing model blob is corrupt')
                print(f'Verified model blob: {digest[7:19]}', flush=True)
                return
            except (requests.RequestException, OSError, ValueError) as e:
                print(f'Model blob retry: {digest[7:19]} {type(e).__name__} ({attempt + 1}/16)', flush=True)
                time.sleep(min(2 ** attempt, 15))
        raise RuntimeError('Model blob download failed: ' + digest[7:19])

    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(fetch_blob, [manifest['config']] + manifest['layers']))
    # A separately started Ollama instance may prune unregistered blobs.
    for layer in [manifest['config']] + manifest['layers']:
        if not (blob_root / layer['digest'].replace(':', '-')).exists():
            fetch_blob(layer)
    installed = model_root / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen3.5' / '4b'
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_bytes(response.content)
    record = json.loads(MANIFEST.read_text('utf-8')) if MANIFEST.exists() else {}
    record['qwen3.5:4b'] = {'url': registry + '/manifests/4b',
                            'manifest_sha256': hashlib.sha256(response.content).hexdigest(),
                            'blobs': [manifest['config']] + manifest['layers']}
    MANIFEST.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Qwen3.5:4b model installed and all hashes verified', flush=True)

def main():
    if ROOT.drive.upper() == 'C:':
        raise SystemExit('请在 E 盘的项目目录运行下载，避免将模型和缓存写入 C 盘')
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('component', choices=['speech', 'ollama', 'model', 'aria2'])
    args = p.parse_args()
    if args.component == 'model':
        download_local_model()
    elif args.component == 'aria2':
        asset = download('https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip', CACHE / 'aria2-1.37.0-win-64bit-build1.zip', 1_000_000)
        dest = RUNTIME / 'aria2'
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(asset) as z:
            for entry in z.infolist():
                if not (dest / entry.filename).resolve().is_relative_to(dest.resolve()):
                    raise ValueError('Unsafe archive path')
            if z.testzip() is not None: raise ValueError('Invalid aria2 archive')
            z.extractall(dest)
        print('Official aria2 download helper installed', flush=True)
    elif args.component == 'speech':
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

