"""RunPod Serverless worker: script.json turns -> MisoTTS 8B audio -> R2 -> URL.

The MISO 8B model runs HERE, on RunPod's GPU -- never on the user's machine.
Input job:  {"input": {"turns": [{"speaker_id": 0|1, "text": "..."}, ...], "name": "..."}}
Output:     {"url": <presigned R2 url>, "key": ..., "seconds": ..., "turns": ...}
"""

import os
import tempfile
import time

import boto3
import runpod
import torch
import torchaudio
from generator import DEFAULT_MISO_TTS_REPO_ID, Segment, load_miso_8b

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
# The reference script keeps ALL prior audio as context, which blows up memory/time
# over a 20-min episode. We window to the last N turns -- enough for prosody continuity.
CONTEXT_WINDOW = int(os.getenv("MISO_CONTEXT_WINDOW", "6"))

print(f"[boot] loading MisoTTS on {DEVICE} ...", flush=True)
_t0 = time.time()
generator = load_miso_8b(
    DEVICE, model_path_or_repo_id=os.getenv("MISO_REPO_ID", DEFAULT_MISO_TTS_REPO_ID)
)
print(f"[boot] loaded in {time.time() - _t0:.1f}s, sample_rate={generator.sample_rate}", flush=True)


def _max_ms(text: str) -> int:
    """A per-turn audio cap (~420 ms/word) so a turn can't run away."""
    return min(45_000, max(8_000, len(text.split()) * 420))


def _render(turns) -> torch.Tensor:
    segments: list[Segment] = []
    for i, t in enumerate(turns):
        spk = int(t["speaker_id"])
        text = t["text"]
        audio = generator.generate(
            text=text,
            speaker=spk,
            context=segments[-CONTEXT_WINDOW:],
            max_audio_length_ms=_max_ms(text),
        )
        segments.append(Segment(text=text, speaker=spk, audio=audio))
        print(f"[render] turn {i + 1}/{len(turns)} spk={spk} {len(text.split())}w", flush=True)
    return torch.cat([s.audio for s in segments], dim=0)


def _r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def handler(job):
    inp = job.get("input") or {}
    turns = inp.get("turns")
    if not turns:
        return {"error": "no 'turns' in input"}
    name = (inp.get("name") or f"episode-{int(time.time())}").replace("/", "__")

    audio = _render(turns)
    path = os.path.join(tempfile.gettempdir(), f"{name}.wav")
    torchaudio.save(path, audio.unsqueeze(0).cpu(), generator.sample_rate)
    with open(path, "rb") as f:
        data = f.read()

    bucket, key = os.environ["R2_BUCKET"], f"{name}.wav"
    s3 = _r2()
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="audio/wav")
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=7 * 24 * 3600
    )
    return {
        "url": url,
        "key": key,
        "seconds": round(audio.shape[0] / generator.sample_rate, 1),
        "turns": len(turns),
    }


runpod.serverless.start({"handler": handler})
