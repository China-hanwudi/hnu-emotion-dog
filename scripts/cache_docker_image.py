"""Cache verified Docker Hub layers and build a standard docker-load archive.

Uses the Windows HTTPS client when the WSL registry connection is unreliable.
Registry content hashes and the uncompressed rootfs hashes are both checked.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from download_chunks import download_chunks

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / '04_下载缓存' / 'docker-images'


def cache_image(image):
    if ROOT.drive.upper() == 'C:':
        raise ValueError('请在 E 盘的项目目录下载镜像')
    if not re.fullmatch(r'[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*:[a-zA-Z0-9_.-]+', image):
        raise ValueError('Expected a Docker Hub repository:tag')
    name, tag = image.rsplit(':', 1)
    host = 'registry-1.docker.io'
    if name.startswith('cr.weaviate.io/'):
        # The official Weaviate registry challenges against Docker Hub for
        # this same repository. Use its upstream endpoint to avoid proxy 429s.
        name = name.split('/', 1)[1]
    elif '/' in name and '.' in name.split('/', 1)[0]:
        raise ValueError('Only Docker Hub and the official Weaviate registry are supported')
    repository = name if '/' in name else 'library/' + name
    directory = CACHE / image.replace('/', '_').replace(':', '_')
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / 'image.tar'
    complete = directory / 'verified.json'
    if archive.exists() and complete.exists():
        record = json.loads(complete.read_text('utf-8'))
        with archive.open('rb') as f:
            archive_hash = hashlib.file_digest(f, 'sha256').hexdigest()
        if record.get('archive_sha256') == archive_hash:
            print('Verified image archive already available: ' + image, flush=True)
            return archive
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(
        total=6, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))))
    headers = {'Accept': ', '.join(('application/vnd.oci.image.index.v1+json',
                   'application/vnd.docker.distribution.manifest.list.v2+json',
                   'application/vnd.oci.image.manifest.v1+json',
                   'application/vnd.docker.distribution.manifest.v2+json'))}
    def refresh_token():
        token = session.get('https://auth.docker.io/token', params={
            'service': 'registry.docker.io', 'scope': 'repository:' + repository + ':pull'
        }, timeout=30)
        token.raise_for_status()
        headers['Authorization'] = 'Bearer ' + token.json()['token']
    refresh_token()
    registry = 'https://' + host + '/v2/' + repository

    def get_manifest(ref):
        r = session.get(registry + '/manifests/' + ref, headers=headers, timeout=45)
        r.raise_for_status()
        digest = 'sha256:' + hashlib.sha256(r.content).hexdigest()
        expected = ref if ref.startswith('sha256:') else r.headers.get('Docker-Content-Digest')
        if expected and expected != digest:
            raise ValueError('Registry manifest SHA256 mismatch')
        return r.json(), digest

    manifest, manifest_digest = get_manifest(tag)
    if 'manifests' in manifest:
        descriptor = next(x for x in manifest['manifests']
                          if x.get('platform', {}).get('architecture') == 'amd64'
                          and x['platform']['os'] == 'linux')
        manifest, manifest_digest = get_manifest(descriptor['digest'])

    def fetch_blob(descriptor):
        digest = descriptor['digest']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('Unsupported blob digest')
        target = directory / digest[7:]
        partial = target.with_suffix('.part')
        if target.exists():
            with target.open('rb') as f:
                actual = hashlib.file_digest(f, 'sha256').hexdigest()
            if target.stat().st_size != descriptor['size'] or actual != digest[7:]:
                target.replace(directory / (target.name + '.damaged.' + str(time.time_ns())))
                print('Damaged image blob preserved: ' + digest[7:19], flush=True)
        for attempt in range(16):
            try:
                if not target.exists():
                    if descriptor['size'] > 50_000_000:
                        refresh_token()
                        # Obtain the registry's current redirect with TLS verification;
                        # registry authorization is not sent to the download helper.
                        with session.get(registry + '/blobs/' + digest, headers=headers,
                                         stream=True, timeout=(30, 120)) as response:
                            response.raise_for_status()
                            download_url = response.url
                        download_chunks(download_url, target, digest[7:], descriptor['size'])
                        continue
                    offset = partial.stat().st_size if partial.exists() else 0
                    refresh_token()
                    request_headers = {**headers, **({'Range': f'bytes={offset}-'} if offset else {})}
                    with session.get(registry + '/blobs/' + digest, headers=request_headers,
                                     stream=True, timeout=(30, 120)) as r:
                        r.raise_for_status()
                        append = offset > 0 and r.status_code == 206
                        if not append: offset = 0
                        last = time.monotonic()
                        with partial.open('ab' if append else 'wb') as f:
                            for chunk in r.iter_content(1024 * 1024):
                                f.write(chunk)
                                offset += len(chunk)
                                if time.monotonic() - last > 15:
                                    print(f'{image} {digest[7:19]}: {offset // 1048576}/{descriptor["size"] // 1048576} MiB', flush=True)
                                    last = time.monotonic()
                    if partial.stat().st_size != descriptor['size']:
                        raise ValueError('Incomplete image blob')
                    with partial.open('rb') as f:
                        actual = hashlib.file_digest(f, 'sha256').hexdigest()
                    if actual != digest[7:]:
                        partial.unlink()
                        raise ValueError('Image blob SHA256 mismatch')
                    partial.replace(target)
                with target.open('rb') as f:
                    actual = hashlib.file_digest(f, 'sha256').hexdigest()
                if target.stat().st_size != descriptor['size'] or actual != digest[7:]:
                    raise ValueError('Cached blob is corrupt')
                print('Verified Docker blob: ' + digest[7:19], flush=True)
                return target
            except (requests.RequestException, ValueError, subprocess.SubprocessError) as e:
                print(f'Image retry {image}: {type(e).__name__} ({attempt + 1}/16)', flush=True)
                time.sleep(min(2 ** attempt, 15))
        raise RuntimeError('Cannot download image layer')

    config_path = fetch_blob(manifest['config'])
    config = json.loads(config_path.read_text())
    if config['architecture'] != 'amd64' or config['os'] != 'linux':
        raise ValueError('Unexpected image platform')
    layers = [fetch_blob(x) for x in manifest['layers']]
    diff_ids = config['rootfs']['diff_ids']
    if len(diff_ids) != len(layers):
        raise ValueError('Rootfs layer count mismatch')
    entries = []
    for descriptor, blob, diff_id in zip(manifest['layers'], layers, diff_ids):
        raw = blob.with_suffix('.layer.tar')
        if raw.exists():
            with raw.open('rb') as f:
                valid_raw = 'sha256:' + hashlib.file_digest(f, 'sha256').hexdigest() == diff_id
            if not valid_raw:
                raw.replace(directory / (raw.name + '.damaged.' + str(time.time_ns())))
                print('Damaged extracted layer preserved: ' + diff_id[7:19], flush=True)
        if not raw.exists():
            if descriptor['mediaType'].endswith('+gzip') or descriptor['mediaType'].endswith('.gzip'):
                with gzip.open(blob, 'rb') as source, raw.open('wb') as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
            elif descriptor['mediaType'].endswith('.tar'):
                shutil.copyfile(blob, raw)
            else:
                raise ValueError('Unsupported image layer compression')
        with raw.open('rb') as f:
            if 'sha256:' + hashlib.file_digest(f, 'sha256').hexdigest() != diff_id:
                raise ValueError('Uncompressed rootfs SHA256 mismatch')
        entries.append((raw, diff_id[7:] + '/layer.tar'))
    config_name = manifest['config']['digest'][7:] + '.json'
    docker_manifest = [{'Config': config_name, 'RepoTags': [image],
                        'Layers': [entry[1] for entry in entries]}]
    with tarfile.open(archive.with_suffix('.tmp'), 'w') as output:
        output.add(config_path, arcname=config_name)
        for raw, entry in entries:
            output.add(raw, arcname=entry)
        data = json.dumps(docker_manifest).encode()
        item = tarfile.TarInfo('manifest.json')
        item.size = len(data)
        output.addfile(item, io.BytesIO(data))
    with archive.with_suffix('.tmp').open('r+b') as f:
        f.flush()
        os.fsync(f.fileno())
    archive.with_suffix('.tmp').replace(archive)
    with archive.open('rb') as f:
        archive_hash = hashlib.file_digest(f, 'sha256').hexdigest()
    complete.write_text(json.dumps({'image': image, 'source': registry,
        'manifest_digest': manifest_digest, 'manifest': manifest,
        'archive_sha256': archive_hash}, indent=2), encoding='utf-8')
    print('Docker load archive ready: ' + image, flush=True)
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    arguments = parser.parse_args()
    print(cache_image(arguments.image), flush=True)
