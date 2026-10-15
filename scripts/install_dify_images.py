"""Install verified official images through the existing E-drive WSL runtime."""
from pathlib import Path
import os
import subprocess
import requests
from dotenv import load_dotenv
from cache_docker_image import cache_image

project = Path(__file__).resolve().parents[1]
root = project.parents[1]
load_dotenv(project / '.env')
wsl = ['wsl', '-d', os.getenv('WSL_DISTRO', 'EmotionDogUbuntu'), '-u', 'root', '--exec']
def linux_path(path):
    return subprocess.check_output(wsl + ['wslpath', '-a', str(path)],
        text=True, encoding='utf-8', stderr=subprocess.DEVNULL).strip()
linux_project = linux_path(project)
linux_dify = linux_path(root / '01_项目代码/dify/docker')
images = subprocess.check_output(wsl + ['docker', 'compose',
    '--project-directory', linux_dify, '-f', linux_dify + '/docker-compose.yaml',
    '-f', linux_project + '/deploy/compose.local.yaml', 'config', '--images'],
    text=True, encoding='utf-8', stderr=subprocess.DEVNULL).splitlines()
cache_root = root / '04_下载缓存/docker-images'
def has_archive(image):
    return (cache_root / image.replace('/', '_').replace(':', '_') / 'verified.json').exists()

failures = []
for image in sorted(dict.fromkeys(images), key=lambda name: not has_archive(name)):
    print('Preparing image: ' + image, flush=True)
    probe = subprocess.run(wsl + ['docker', 'image', 'inspect', image],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode == 0:
        print('Installed image preserved: ' + image, flush=True)
        continue
    try:
        archive = cache_image(image)
        linux_archive = linux_path(archive)
        subprocess.run(wsl + ['docker', 'load', '-i', linux_archive], check=True)
    except (requests.RequestException, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        failures.append(image)
        print(f'Image remains pending: {image} ({type(error).__name__})', flush=True)
if failures:
    raise SystemExit('Images not yet installed: ' + ', '.join(failures))
print('All Dify images installed', flush=True)
