"""Resume a large official artifact and verify its publisher SHA256."""
import hashlib
import os
from pathlib import Path
import subprocess
import urllib.request


def download_verified(url: str, target: Path, digest: str, runtime: Path, log: Path):
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid publisher digest')
    if target.exists():
        with target.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() == digest:
                return target
        raise ValueError('Existing installer checksum mismatch')
    aria = next((runtime / 'aria2').glob('**/aria2c.exe'))
    partial = target.with_suffix(target.suffix + '.part')
    arguments = [str(aria), '--no-conf', '--continue=true',
                 '--max-connection-per-server=4', '--split=4', '--min-split-size=8M',
                 '--max-tries=20', '--retry-wait=5', '--timeout=90',
                 '--file-allocation=none', '--check-integrity=true',
                 '--checksum=sha-256=' + digest, '--summary-interval=30',
                 '--show-console-readout=false', '--console-log-level=warn',
                 '--download-result=hide', '--dir=' + str(target.parent),
                 '--out=' + partial.name]
    proxy = urllib.request.getproxies().get('https')
    if proxy:
        arguments.append('--all-proxy=' + proxy)
    arguments.append(url)
    print('Verified artifact download: ' + target.name, flush=True)
    with log.open('w', encoding='utf-8') as output:
        subprocess.run(arguments, stdout=output, stderr=subprocess.STDOUT, check=True)
    with partial.open('r+b') as source:
        source.flush()
        os.fsync(source.fileno())
    with partial.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
            raise ValueError('Publisher SHA256 mismatch')
    partial.replace(target)
    print('Publisher checksum verified: ' + target.name, flush=True)
    return target
