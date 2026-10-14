import asyncio
import argparse
import json
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.speech import transcribe, synthesize
from app.dialogue import generate
from app.robot import RobotClient, RobotError

async def main(with_robot=False):
    report = {}
    sample = ROOT / '06_测试素材' / 'sensevoice_zh.wav'
    if sample.exists(): report['real_asr'] = transcribe(sample.read_bytes())
    report['tts_file'] = synthesize('你好，我是小伴。今天有什么想分享的吗？')
    try: report['llm'] = await generate('今天实验又失败了，我有些难过。', 'sad', None, [])
    except Exception as e: report['llm_error'] = type(e).__name__
    if with_robot:
        try: report['robot_info'] = await RobotClient().info()
        except RobotError as e: report['robot_error'] = str(e)
    target = ROOT / '05_日志' / 'verification.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-robot', action='store_true')
    asyncio.run(main(parser.parse_args().with_robot))
