"""Bench a hosted cloning TTS on bench/base_script.json with the Grant/Speed clips.

ElevenLabs backend (instant voice cloning). Needs ELEVENLABS_API_KEY in .env.
Unlike MISO, ElevenLabs clones better from the FULL recordings (30-50s), so we
feed the whole clip.

  uv run --with elevenlabs dev-podcast-bench --script bench/base_script.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from .render import _stitch

ROOT = Path(__file__).resolve().parents[2]
SENIOR_CLIP = ROOT / "src/dev_podcast/voices/GrantSanderson.wav"
JUNIOR_CLIP = ROOT / "src/dev_podcast/voices/iShowSpeed.wav"


def eleven_bench(script_path: Path, out_wav: Path, model_id: str = "eleven_multilingual_v2") -> Path:
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    print("cloning voices (instant voice cloning) ...")
    senior = client.voices.ivc.create(name="bench-senior-grant", files=[open(SENIOR_CLIP, "rb")]).voice_id
    junior = client.voices.ivc.create(name="bench-junior-speed", files=[open(JUNIOR_CLIP, "rb")]).voice_id
    voice_for = {0: senior, 1: junior}

    turns = json.loads(script_path.read_text())["turns"]
    tmp = Path(tempfile.mkdtemp(prefix="eleven_"))
    wavs = []
    for i, t in enumerate(turns):
        audio = client.text_to_speech.convert(
            voice_id=voice_for[int(t["speaker_id"])], text=t["text"],
            model_id=model_id, output_format="mp3_44100_128",
        )
        mp3 = tmp / f"{i:03d}.mp3"
        with open(mp3, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        wav = tmp / f"{i:03d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ar", "24000", "-ac", "1", str(wav)], check=True)
        wavs.append(wav)
        print(f"  line {i + 1}/{len(turns)} (speaker {t['speaker_id']})")
    _stitch(wavs, out_wav)
    print(f"saved: {out_wav}")
    return out_wav


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="dev-podcast-bench")
    p.add_argument("--script", type=Path, default=ROOT / "bench/base_script.json")
    p.add_argument("--out", type=Path, default=ROOT / "bench/eleven_base.wav")
    p.add_argument("--model", default="eleven_multilingual_v2")
    args = p.parse_args()
    if not os.getenv("ELEVENLABS_API_KEY"):
        raise SystemExit("ELEVENLABS_API_KEY not in .env")
    eleven_bench(args.script, args.out, args.model)
    return 0


if __name__ == "__main__":
    main()
