"""RunPod Serverless worker: script.json turns -> MisoTTS 8B audio -> R2 -> URL.

The MISO 8B model runs HERE, on RunPod's GPU -- never on the user's machine.

Design note: the model is loaded LAZILY inside the job (not at import), and the
handler wraps everything in try/except. So the worker boots and reports `ready`
immediately, and any failure (model download, GPU, deps) comes back as a readable
error in the job result instead of an invisible startup crash-loop.

Input job:  {"input": {"turns": [{"speaker_id": 0|1, "text": "..."}, ...], "name": "..."}}
Output:     {"url": <presigned R2 url>, "key": ..., "seconds": ..., "turns": ...}
            or {"error": "...", "trace": "..."} on failure.
"""

import os
import tempfile
import time
import traceback

import runpod

# The reference script keeps ALL prior audio as context, which blows up over a 20-min
# episode. Window to the last N turns -- enough for prosody continuity.
CONTEXT_WINDOW = int(os.getenv("MISO_CONTEXT_WINDOW", "6"))

_generator = None  # loaded on first job


def _get_generator():
    global _generator
    if _generator is None:
        import torch
        from generator import DEFAULT_MISO_TTS_REPO_ID, load_miso_8b

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[boot] loading MisoTTS on {device} (first job cold-starts) ...", flush=True)
        t0 = time.time()
        _generator = load_miso_8b(
            device, model_path_or_repo_id=os.getenv("MISO_REPO_ID", DEFAULT_MISO_TTS_REPO_ID)
        )
        print(f"[boot] loaded in {time.time() - t0:.1f}s, sample_rate={_generator.sample_rate}", flush=True)
    return _generator


def _max_ms(text: str) -> int:
    return min(45_000, max(8_000, len(text.split()) * 420))


def _render(gen, turns):
    import torch
    from generator import Segment

    segments = []
    for i, t in enumerate(turns):
        spk = int(t["speaker_id"])
        text = t["text"]
        audio = gen.generate(
            text=text, speaker=spk,
            context=segments[-CONTEXT_WINDOW:], max_audio_length_ms=_max_ms(text),
        )
        segments.append(Segment(text=text, speaker=spk, audio=audio))
        print(f"[render] turn {i + 1}/{len(turns)} spk={spk} {len(text.split())}w", flush=True)
    return torch.cat([s.audio for s in segments], dim=0)


def _upload(data: bytes, key: str) -> str:
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"]
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="audio/wav")
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=7 * 24 * 3600
    )


def handler(job):
    try:
        import torchaudio

        inp = job.get("input") or {}
        turns = inp.get("turns")
        if not turns:
            return {"error": "no 'turns' in input"}
        name = (inp.get("name") or f"episode-{int(time.time())}").replace("/", "__")

        gen = _get_generator()
        audio = _render(gen, turns)

        path = os.path.join(tempfile.gettempdir(), f"{name}.wav")
        torchaudio.save(path, audio.unsqueeze(0).cpu(), gen.sample_rate)
        with open(path, "rb") as f:
            data = f.read()

        url = _upload(data, f"{name}.wav")
        return {
            "url": url,
            "key": f"{name}.wav",
            "seconds": round(audio.shape[0] / gen.sample_rate, 1),
            "turns": len(turns),
        }
    except Exception as e:
        tb = traceback.format_exc()
        print("[error]\n" + tb, flush=True)
        return {"error": str(e), "trace": tb[-1800:]}


runpod.serverless.start({"handler": handler})
