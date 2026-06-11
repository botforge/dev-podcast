"""RunPod worker: Fish Speech S2 voice-cloning TTS.

Same input contract as the MISO worker:
  {"input": {"turns":[{speaker_id,text}], "refs":[{speaker_id,audio_b64,text}], "name"}}
Runs fish-speech's api_server locally (loads the 4B model once), POSTs each turn with
the matching speaker's reference clip, concatenates, uploads wav to R2.

Errors are returned in the job result (not a silent crash), like the MISO worker.
"""

import base64
import os
import subprocess
import time
import traceback
import urllib.error
import urllib.request

import runpod

PORT = 8080
TTS_URL = f"http://127.0.0.1:{PORT}/v1/tts"
CKPT = os.getenv("FISH_CKPT", "/runpod-volume/s2-pro")
_proc = None


def _ensure_weights():
    if not os.path.exists(os.path.join(CKPT, "codec.pth")):
        print("[boot] downloading fishaudio/s2-pro ...", flush=True)
        from huggingface_hub import snapshot_download
        snapshot_download("fishaudio/s2-pro", local_dir=CKPT,
                          token=os.getenv("HF_TOKEN"))


def _ensure_server():
    global _proc
    if _proc is None:
        _ensure_weights()
        print("[boot] starting fish api_server ...", flush=True)
        _proc = subprocess.Popen(
            ["python", "tools/api_server.py",
             "--llama-checkpoint-path", CKPT,
             "--decoder-checkpoint-path", os.path.join(CKPT, "codec.pth"),
             "--listen", f"127.0.0.1:{PORT}"],
            cwd="/app/fish-speech",
        )
    import ormsgpack
    probe = ormsgpack.packb({"text": "ready", "references": [], "format": "wav", "streaming": False})
    for _ in range(300):  # up to ~10 min for model load
        try:
            req = urllib.request.Request(TTS_URL, data=probe,
                                         headers={"content-type": "application/msgpack"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
            return
        except urllib.error.HTTPError:
            return  # server answered (even an error) -> it's up
        except Exception:
            if _proc.poll() is not None:
                raise RuntimeError("fish api_server exited during startup")
            time.sleep(2)
    raise RuntimeError("fish api_server never became ready")


def _tts(text, audio_bytes, ref_text) -> bytes:
    import ormsgpack
    refs = [{"audio": audio_bytes, "text": ref_text}] if audio_bytes else []
    body = ormsgpack.packb({"text": text, "references": refs, "format": "wav", "streaming": False})
    req = urllib.request.Request(TTS_URL, data=body,
                                 headers={"content-type": "application/msgpack"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def _concat(wavs):
    import io
    import wave
    if len(wavs) == 1:
        return wavs[0]
    out = io.BytesIO()
    with wave.open(out, "wb") as o:
        params = None
        for w in wavs:
            with wave.open(io.BytesIO(w), "rb") as r:
                if params is None:
                    params = r.getparams()
                    o.setparams(params)
                o.writeframes(r.readframes(r.getnframes()))
    return out.getvalue()


def _upload(data: bytes, key: str) -> str:
    import boto3
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    bucket = os.environ["R2_BUCKET"]
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="audio/wav")
    return s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=7 * 24 * 3600)


def handler(job):
    try:
        _ensure_server()
        inp = job.get("input") or {}
        turns = inp.get("turns")
        if not turns:
            return {"error": "no 'turns' in input"}
        refs = {int(r["speaker_id"]): (base64.b64decode(r["audio_b64"]), r.get("text", ""))
                for r in (inp.get("refs") or [])}
        name = (inp.get("name") or f"ep-{int(time.time())}").replace("/", "__")
        outs = []
        for t in turns:
            audio, rtext = refs.get(int(t["speaker_id"]), (b"", ""))
            outs.append(_tts(t["text"], audio, rtext))
            print(f"[render] spk={t['speaker_id']} {len(t['text'].split())}w", flush=True)
        url = _upload(_concat(outs), f"{name}.wav")
        return {"url": url, "key": f"{name}.wav", "turns": len(turns)}
    except Exception as e:
        tb = traceback.format_exc()
        print("[error]\n" + tb, flush=True)
        return {"error": str(e), "trace": tb[-1800:]}


runpod.serverless.start({"handler": handler})
