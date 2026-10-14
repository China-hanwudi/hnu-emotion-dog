"""Pull official Compose images one at a time, retaining successful pulls."""
import argparse
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--directory', required=True)
p.add_argument('--override', required=True)
args = p.parse_args()
compose = ['docker', 'compose', '-f', 'docker-compose.yaml', '-f', args.override]
images = subprocess.check_output(compose + ['config', '--images'],
                                 cwd=args.directory, text=True).splitlines()
for image in dict.fromkeys(images):
    available = subprocess.run(['docker', 'image', 'inspect', image],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if available.returncode == 0:
        print('Image already installed: ' + image, flush=True)
        continue
    for attempt in range(6):
        print(f'Pulling {image} (attempt {attempt + 1}/6)', flush=True)
        result = subprocess.run(['docker', 'pull', image], cwd=args.directory)
        if result.returncode == 0:
            break
        time.sleep(min(2 ** attempt, 15))
    else:
        raise RuntimeError('Image download incomplete: ' + image)
print('All Dify images downloaded', flush=True)
