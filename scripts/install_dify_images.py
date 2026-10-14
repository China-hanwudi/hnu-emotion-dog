"""Install verified official images through the existing E-drive WSL runtime."""
from pathlib import Path
import os
import subprocess
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
for image in dict.fromkeys(images):
    probe = subprocess.run(wsl + ['docker', 'image', 'inspect', image],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode == 0:
        print('Installed image preserved: ' + image, flush=True)
        continue
    archive = cache_image(image)
    linux_archive = linux_path(archive)
    subprocess.run(wsl + ['docker', 'load', '-i', linux_archive], check=True)
print('All Dify images installed', flush=True)
