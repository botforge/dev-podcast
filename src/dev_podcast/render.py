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
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

API = "https://api.runpod.ai/v2"


def _req(url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def render(script_path: Path, out_wav: Path | None, poll: int = 5, timeout: int = 2400) -> dict:
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_ENDPOINT_ID"]
    script = json.loads(script_path.read_text())
    name = script.get("repo", "episode").replace("/", "__")

    print(f"Submitting {len(script['turns'])} turns to RunPod endpoint {endpoint} ...")
    job = _req(f"{API}/{endpoint}/run", key, {"input": {"turns": script["turns"], "name": name}})
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


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="dev-podcast-render")
    p.add_argument("script", type=Path, help="path to a script.json")
    p.add_argument("--out", type=Path, default=None, help="output .wav (default: alongside script.json)")
    args = p.parse_args()
    for var in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID"):
        if not os.getenv(var):
            raise SystemExit(f"missing {var} in .env")
    render(args.script, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
