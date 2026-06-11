"""Send a script.json to the RunPod MisoTTS endpoint and download the audio.

Nothing heavy runs locally -- this POSTs JSON, polls for the job, and downloads
the finished .wav. The model runs on RunPod.

  dev-podcast-render out/owner__repo/script.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from dotenv import load_dotenv

API = "https://api.runpod.ai/v2"


def _req(url: str, key: str, body: dict | None = None, retries: int = 4) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.URLError:  # transient network drop -> retry
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def _voice_refs(voices_dir: Path | None) -> list | None:
    """Read senior/junior reference clips (wav + matching .txt) and base64-encode them."""
    if not voices_dir:
        return None
    import base64
    refs = []
    for spk, who in ((0, "senior"), (1, "junior")):
        wav, txt = voices_dir / f"{who}.wav", voices_dir / f"{who}.txt"
        refs.append({"speaker_id": spk, "text": txt.read_text().strip(),
                     "audio_b64": base64.b64encode(wav.read_bytes()).decode()})
    return refs


def render(script_path: Path, out_wav: Path | None, refs: list | None = None,
           poll: int = 5, timeout: int = 2400) -> dict:
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_ENDPOINT_ID"]
    script = json.loads(script_path.read_text())
    name = script.get("repo", "episode").replace("/", "__")

    inp = {"turns": script["turns"], "name": name}
    if refs:
        inp["refs"] = refs
    print(f"Submitting {len(script['turns'])} turns to RunPod endpoint {endpoint} ...")
    job = _req(f"{API}/{endpoint}/run", key, {"input": inp})
    job_id = job["id"]
    print(f"job: {job_id}  (first run cold-starts the model -- can take a few minutes)")

    t0 = time.time()
    while True:
        st = _req(f"{API}/{endpoint}/status/{job_id}", key)
        status = st.get("status")
        if status == "COMPLETED":
            out = st["output"]
            dest = out_wav or (script_path.parent / "episode.wav")
            urllib.request.urlretrieve(out["url"], dest)
            print(f"done: {out.get('seconds')}s of audio, {out.get('turns')} turns")
            print(f"saved: {dest}")
            print(f"url:   {out['url']}")
            return out
        if status in ("FAILED", "CANCELLED"):
            print(json.dumps(st, indent=2), file=sys.stderr)
            raise SystemExit(f"render {status}")
        if time.time() - t0 > timeout:
            raise SystemExit(f"timed out after {timeout}s (last status: {status})")
        print(f"  {status} ... {int(time.time() - t0)}s")
        time.sleep(poll)


def _stitch(in_paths: list[Path], out_path: Path, gap_ms: int = 200) -> float:
    """Concatenate per-turn WAVs (in order) with a small silence gap between."""
    with wave.open(str(in_paths[0]), "rb") as w0:
        nch, sw, sr = w0.getnchannels(), w0.getsampwidth(), w0.getframerate()
    gap = b"\x00" * (nch * sw * int(sr * gap_ms / 1000))
    total = 0
    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(nch); out.setsampwidth(sw); out.setframerate(sr)
        for i, p in enumerate(in_paths):
            with wave.open(str(p), "rb") as w:
                frames = w.readframes(w.getnframes())
            out.writeframes(frames); total += len(frames)
            if i != len(in_paths) - 1:
                out.writeframes(gap); total += len(gap)
    return total / (nch * sw * sr)


def render_parallel(script_path: Path, out_wav: Path | None, refs: list | None = None,
                    poll: int = 5, timeout: int = 3600) -> dict:
    """Render every turn as its own RunPod job (refs-only context, independent),
    in parallel across workers, then stitch the WAVs in order."""
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_ENDPOINT_ID"]
    script = json.loads(script_path.read_text())
    turns = script["turns"]
    base = script.get("repo", "episode").replace("/", "__")

    print(f"Submitting {len(turns)} per-turn jobs to RunPod (parallel) ...")
    jobs = []  # (index, job_id, name)
    for i, t in enumerate(turns):
        name = f"{base}__t{i:03d}"
        inp = {"turns": [t], "name": name}
        if refs:
            inp["refs"] = refs
        j = _req(f"{API}/{endpoint}/run", key, {"input": inp})
        jobs.append((i, j["id"], name))

    pending = {jid: i for i, jid, _ in jobs}
    urls: dict[int, str] = {}
    t0 = time.time()
    while pending:
        for jid in list(pending):
            st = _req(f"{API}/{endpoint}/status/{jid}", key)
            s = st.get("status")
            if s == "COMPLETED":
                out = st["output"]
                if "url" not in out:
                    raise SystemExit(f"turn {pending[jid]} job error: {out}")
                urls[pending.pop(jid)] = out["url"]
            elif s in ("FAILED", "CANCELLED"):
                raise SystemExit(f"turn {pending[jid]} {s}: {st}")
        done = len(urls)
        print(f"  {done}/{len(turns)} turns done ... {int(time.time() - t0)}s")
        if time.time() - t0 > timeout:
            raise SystemExit(f"timed out; {done}/{len(turns)} done")
        if pending:
            time.sleep(poll)

    tmp = Path(tempfile.mkdtemp(prefix="devpod_"))
    paths = []
    for i in range(len(turns)):
        p = tmp / f"t{i:03d}.wav"
        urllib.request.urlretrieve(urls[i], p)
        paths.append(p)
    dest = out_wav or (script_path.parent / "episode.wav")
    secs = _stitch(paths, dest)
    print(f"done: stitched {len(turns)} turns -> {secs:.1f}s of audio")
    print(f"saved: {dest}")
    return {"seconds": secs, "turns": len(turns)}


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="dev-podcast-render")
    p.add_argument("script", type=Path, help="path to a script.json")
    p.add_argument("--out", type=Path, default=None, help="output .wav (default: alongside script.json)")
    p.add_argument("--parallel", action="store_true", help="render each turn as its own job, in parallel (fast)")
    p.add_argument("--voices", type=Path, default=None,
                   help="dir with senior.wav/.txt + junior.wav/.txt to use as reference voices")
    args = p.parse_args()
    for var in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID"):
        if not os.getenv(var):
            raise SystemExit(f"missing {var} in .env")
    refs = _voice_refs(args.voices)
    (render_parallel if args.parallel else render)(args.script, args.out, refs=refs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
