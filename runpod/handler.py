"""RunPod Serverless worker: script.json turns -> MisoTTS 8B audio -> R2 -> URL.

The MISO 8B model runs HERE, on RunPod's GPU -- never on the user's machine.

Voices: MISO has no built-in voices -- distinct speakers come from REFERENCE audio.
We prime speaker 0 and speaker 1 each with a short reference clip (voice cloning),
seeded into the generation context, so the two voices stay distinct and consistent.

Model is loaded LAZILY inside the job with try/except, so the worker boots ready
fast and any failure returns as a readable error in the job result.

Input job:  {"input": {"turns": [{"speaker_id": 0|1, "text": "..."}, ...], "name": "..."}}
Output:     {"url": <presigned R2 url>, "key": ..., "seconds": ..., "turns": ...}
            or {"error": "...", "trace": "..."} on failure.
"""

import os
import tempfile
import time
import traceback

import runpod

# Total seconds of audio context (reference clips + recent turns) fed per generation.
# Kept well under MISO's sequence limit; references are always included.
MAX_CONTEXT_SEC = float(os.getenv("MISO_MAX_CONTEXT_SEC", "55"))

# Reference voice per speaker id: (file under voices/, transcript of the clip).
REF_VOICES = {
    0: ("voices/voiceA.wav", "I had that curiosity beside me at this moment."),
    1: ("voices/voiceB.wav", "He hoped there would be stew for dinner, turnips and carrots and bruised potatoes."),
}

_generator = None
_refs = None


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


def _wav_to_seg(gen, wav, sr, speaker, text):
    import torchaudio
    from generator import Segment
    wav = wav.mean(dim=0) if wav.dim() > 1 else wav
    if sr != gen.sample_rate:
        wav = torchaudio.functional.resample(wav, sr, gen.sample_rate)
    return Segment(text=text, speaker=int(speaker), audio=wav)


def _load_refs(gen):
    """Default baked reference clips (used when the job doesn't supply its own)."""
    global _refs
    if _refs is None:
        import torchaudio
        here = os.path.dirname(os.path.abspath(__file__))
        segs = {}
        for spk, (rel, text) in REF_VOICES.items():
            wav, sr = torchaudio.load(os.path.join(here, rel))
            segs[spk] = _wav_to_seg(gen, wav, sr, spk, text)
        _refs = segs
    return _refs


def _refs_from_input(gen, refs_in):
    """Per-job reference clips: [{speaker_id, audio_b64 (wav), text}, ...]."""
    import base64
    import tempfile
    import torchaudio
    segs = {}
    for r in refs_in:
        path = os.path.join(tempfile.gettempdir(), f"ref_{r['speaker_id']}.wav")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["audio_b64"]))
        wav, sr = torchaudio.load(path)
        segs[int(r["speaker_id"])] = _wav_to_seg(gen, wav, sr, r["speaker_id"], r.get("text", ""))
        print(f"[refs] job speaker {r['speaker_id']}: {segs[int(r['speaker_id'])].audio.shape[0]/gen.sample_rate:.1f}s", flush=True)
    return segs


def _max_ms(text: str) -> int:
    return min(45_000, max(8_000, len(text.split()) * 420))


def _context(refs, segments, sr):
    """References (always) + as many recent turns as fit the audio-seconds budget."""
    ctx = [refs[0], refs[1]]
    used = sum(s.audio.shape[0] for s in ctx) / sr
    recent = []
    for s in reversed(segments):
        dur = s.audio.shape[0] / sr
        if used + dur > MAX_CONTEXT_SEC:
            break
        used += dur
        recent.append(s)
    return ctx + list(reversed(recent))


def _render(gen, turns, refs):
    import torch
    from generator import Segment
    segments = []
    for i, t in enumerate(turns):
        spk = int(t["speaker_id"])
        text = t["text"]
        audio = gen.generate(
            text=text, speaker=spk,
            context=_context(refs, segments, gen.sample_rate),
            max_audio_length_ms=_max_ms(text),
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
        refs_in = inp.get("refs")
        refs = _refs_from_input(gen, refs_in) if refs_in else _load_refs(gen)
        audio = _render(gen, turns, refs)

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
