"""Create the project's own E-drive Ubuntu runtime, preserving other distros."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from download_assets import ROOT, CACHE, RUNTIME
from download_verified import download_verified

DISTRO = 'EmotionDogUbuntu'


def run_wsl(*arguments, check=True):
    result = subprocess.run(['wsl', *arguments], capture_output=True)
    for data in (result.stdout, result.stderr):
        if data:
            print(data.decode('utf-16-le' if b'\0' in data else 'utf-8',
                              errors='replace').strip(), flush=True)
    if check:
        result.check_returncode()
    return result


def main():
    if ROOT.drive.upper() == 'C:':
        raise SystemExit('请在 E 盘的项目目录运行 Ubuntu 安装')
    listing = subprocess.check_output(['wsl', '--list', '--quiet']).decode('utf-16-le')
    if DISTRO not in listing.split():
        info = requests.get('https://raw.githubusercontent.com/microsoft/WSL/master/'
                            'distributions/DistributionInfo.json', timeout=30)
        info.raise_for_status()
        upstream = next(x for x in info.json()['ModernDistributions']['Ubuntu']
                        if x['Name'] == 'Ubuntu-24.04')['Amd64Url']
        archive = download_verified(upstream['Url'], CACHE / 'ubuntu-24.04-wsl-amd64.wsl',
                                    upstream['Sha256'], RUNTIME, ROOT / '05_日志/ubuntu-download.log')
        with archive.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != upstream['Sha256']:
                raise ValueError('Ubuntu WSL official checksum mismatch')
        destination = ROOT / '02_运行环境' / 'wsl' / DISTRO
        destination.mkdir(parents=True, exist_ok=True)
        run_wsl('--import', DISTRO, str(destination), str(archive), '--version', '2')
    run_wsl('-d', DISTRO, '-u', 'root', '--exec', 'sh', '-c',
            "printf '[boot]\nsystemd=true\n[interop]\nenabled=false\n' > /etc/wsl.conf")
    run_wsl('--terminate', DISTRO)
    env_path = PROJECT / '.env'
    lines = env_path.read_text('utf-8-sig').splitlines()
    lines = [x for x in lines if not x.startswith('WSL_DISTRO=')]
    lines.append('WSL_DISTRO=' + DISTRO)
    env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Project Ubuntu runtime installed on E:', flush=True)
    run_wsl('-d', DISTRO, '-u', 'root', '--exec', 'sh', '-c',
            'ip -4 route show default; command -v python3')


if __name__ == '__main__':
    main()
