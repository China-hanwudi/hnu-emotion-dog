"""Resumable HTTPS ranges using Windows Python's TLS client."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def download_chunks(url: str, target: Path, digest: str, size: int):
    directory = target.parent / (target.name + '.chunks')
    directory.mkdir(exist_ok=True)
    chunk_size = 8 * 1024 * 1024
    count = (size + chunk_size - 1) // chunk_size

    def fetch(index):
        start = index * chunk_size
        end = min(start + chunk_size, size) - 1
        chunk = directory / f'{index:05d}.part'
        verified = chunk.with_suffix('.sha256')
        if chunk.exists() and chunk.stat().st_size == end - start + 1 and verified.exists():
            with chunk.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() == verified.read_text():
                    return chunk
        session = requests.Session()
        session.mount('https://', HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1)))
        try:
            for attempt in range(8):
                try:
                    offset = chunk.stat().st_size if chunk.exists() else 0
                    if offset >= end - start + 1:
                        offset = 0
                    position = start + offset
                    with session.get(url, headers={'Range': f'bytes={position}-{end}'},
                                     stream=True, timeout=(30, 90)) as response:
                        response.raise_for_status()
                        if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {position}-{end}/{size}':
                            raise ValueError('Server did not honor exact HTTPS byte range')
                        with chunk.open('ab' if offset else 'wb') as output:
                            for data in response.iter_content(1024 * 1024):
                                output.write(data)
                            output.flush()
                            os.fsync(output.fileno())
                    if chunk.stat().st_size != end - start + 1:
                        raise ValueError('Incomplete byte range')
                    with chunk.open('rb') as source:
                        verified.write_text(hashlib.file_digest(source, 'sha256').hexdigest())
                    return chunk
                except (requests.RequestException, OSError, ValueError) as error:
                    print(f'Range retry {target.name[:12]} part {index}: {type(error).__name__}', flush=True)
                    if attempt == 7:
                        raise
                    time.sleep(min(2 ** attempt, 10))
        finally:
            session.close()

    print(f'Windows TLS range download: {target.name[:12]} ({size // 1048576} MiB)', flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, index) for index in range(count)]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            print(f'{target.name[:12]}: {done}/{count} ranges verified locally', flush=True)
    temporary = target.with_suffix('.assembled')
    checksum = hashlib.sha256()
    with temporary.open('wb') as output:
        for index in range(count):
            with (directory / f'{index:05d}.part').open('rb') as source:
                while data := source.read(1024 * 1024):
                    output.write(data)
                    checksum.update(data)
        output.flush()
        os.fsync(output.fileno())
    if temporary.stat().st_size != size or checksum.hexdigest() != digest:
        directory.rename(directory.with_name(directory.name + '.damaged.' + str(time.time_ns())))
        raise ValueError('Complete publisher SHA256 mismatch')
    # Read again after forcing the file to disk, so failed storage is detected.
    with temporary.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
            directory.rename(directory.with_name(directory.name + '.damaged.' + str(time.time_ns())))
            raise ValueError('Flushed artifact readback SHA256 mismatch')
    temporary.replace(target)
    return target
