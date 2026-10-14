from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parents[1]
load_dotenv(PROJECT / '.env', override=False)

def flag(name): return os.getenv(name, 'false').lower() in ('1', 'true', 'yes')
MODEL_DIR = Path(os.getenv('MODEL_DIR', str(ROOT / '03_模型')))
LOG_DIR = Path(os.getenv('LOG_DIR', str(ROOT / '05_日志')))
AUDIO_DIR = Path(os.getenv('AUDIO_DIR', str(ROOT / '06_测试素材' / 'generated_audio')))
for p in (LOG_DIR, AUDIO_DIR): p.mkdir(parents=True, exist_ok=True)

