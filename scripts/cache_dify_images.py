"""Prepare the active Dify profile images without requiring a running daemon."""
from pathlib import Path
import yaml
from dotenv import dotenv_values
from cache_docker_image import cache_image

project = Path(__file__).resolve().parents[1]
docker = project.parents[1] / '01_项目代码' / 'dify' / 'docker'
settings = dotenv_values(docker / '.env')
profiles = set((settings.get('COMPOSE_PROFILES') or '').split(','))
compose = yaml.safe_load((docker / 'docker-compose.yaml').read_text('utf-8'))
images = list(dict.fromkeys(service['image'] for service in compose['services'].values()
                           if service.get('image') and
                           (not service.get('profiles') or profiles.intersection(service['profiles']))))
# Finish the already downloaded web layers first.
images.sort(key=lambda image: image != 'langgenius/dify-web:1.17.1')
for image in images:
    cache_image(image)
print('Active Dify profile archives verified', flush=True)
