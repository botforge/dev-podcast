# Deploying the audio half (RunPod Serverless + Cloudflare R2)

The MISO 8B model runs on RunPod's GPU. Your laptop only sends `script.json` and
downloads the finished `.wav`. You set this up once; after that it's one command.

You'll create **two accounts** and collect **six secrets** that go in your local `.env`:
`RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.

---

## 1. Cloudflare R2 (storage for the finished audio)

1. Sign in at <https://dash.cloudflare.com> → **R2** in the sidebar. Enable it (asks for a
   card; storage of a few WAVs is effectively free).
2. **Create bucket** → name it `dev-podcast`. That's your `R2_BUCKET`.
3. Your **Account ID** is on the R2 overview page (right side). That's `R2_ACCOUNT_ID`.
4. **Manage R2 API Tokens** → **Create API token** → permission **Object Read & Write** →
   scope it to the `dev-podcast` bucket → Create. It shows an **Access Key ID** and a
   **Secret Access Key** once. Those are `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`.

Put all four into your local `.env` (uncomment the lines we left there).

## 2. Push this repo to GitHub (so RunPod can build the worker for you)

RunPod builds the Docker image in the cloud from a GitHub repo — no local Docker needed.

```bash
# create an empty repo on github.com first (private is fine), then:
git remote add origin https://github.com/<you>/dev-podcast.git
git push -u origin main
```
`.env` is gitignored, so your secrets do **not** get pushed.

## 3. RunPod (the GPU)

1. Sign up at <https://runpod.io> and add a little credit.
2. **Settings → API Keys → Create** → that's `RUNPOD_API_KEY` for your `.env`.
3. **Storage → Network Volume → Create**: ~50 GB, in a region that has 24 GB GPUs. This
   caches the ~16 GB model so cold starts don't re-download it.
4. **Serverless → New Endpoint → Import Git Repository** → connect GitHub → pick your
   `dev-podcast` repo. Set:
   - **Dockerfile path:** `runpod/Dockerfile`
   - **GPU:** a 24 GB card (RTX 4090 / A5000 / L4) — bf16 fits in 24 GB.
   - **Network volume:** attach the one from step 3 (it mounts at `/runpod-volume`).
   - **Workers:** min 0 (scale to zero), max 1 to start.
   - **Environment variables:** `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
     `R2_BUCKET` (same values as your `.env`).
5. Deploy. RunPod builds the image (several minutes the first time). When it's live, copy
   the **Endpoint ID** → that's `RUNPOD_ENDPOINT_ID` for your `.env`.

## 4. Render

```bash
uv sync   # picks up the new dev-podcast-render command
uv run dev-podcast-render out/fastapi__fastapi/script.json
```

The first call cold-starts the model (downloads weights to the network volume once, then
loads — a few minutes). Later calls are fast. It saves `episode.wav` next to the script and
prints a shareable R2 URL.

---

## Notes / knobs

- **v1 voices:** plain speaker IDs 0 (senior) and 1 (junior). Voice cloning from reference
  clips is a later add (prime each speaker with a short sample for distinct, consistent voices).
- **Context window:** `MISO_CONTEXT_WINDOW` env var (default 6) caps how many prior turns
  feed prosody — keeps a 20-min render from blowing up memory.
- **Cold start:** keep 1 worker "active" (min workers = 1) during a render session if you
  want instant renders; set back to 0 to stop paying when idle.
- **Debugging:** RunPod endpoint → **Logs** shows the `[boot]` / `[render]` prints from the
  handler. If a render fails, that's where the reason is.
