# dev-podcast

Point at a public GitHub repo → a genuine 15–20 min two-voice podcast where a **senior dev
(Teacher)** and a **junior dev (Student)** converse and reach shared understanding, then
(later) render to audio with MisoTTS 8B.

Two separate Claude agents — not one writer. The Teacher knows the repo via the hosted
**DeepWiki MCP** (semantic Q&A, no local clone/index); the Student is code-blind and drives
by asking. The orchestrator only routes turns and stops — it never writes dialogue.

## Two loops

- **Inner loop (this repo, runs locally, no GPU):** repo + persona config → `script.json`
  (+ `wiki.md`, `transcript.txt`). Pure Claude API calls. Iterate here in seconds-to-minutes.
- **Outer loop (RunPod Serverless, later):** `script.json` → MisoTTS 8B → `.wav` → R2.

## Setup (inner loop)

```bash
# 1. Python deps via uv (no model, no GPU)
uv sync                 # or: pip install -e .

# 2. Your Anthropic key
cp .env.example .env    # then put your ANTHROPIC_API_KEY in it
```

## Run

```bash
# Quick start with presets:
uv run dev-podcast facebook/react --student completionist --teacher pair_programmer --minutes 18

# Tune the personas by hand:
uv run dev-podcast facebook/react --write-config react.yaml   # dump editable sliders
#   ...edit react.yaml...
uv run dev-podcast facebook/react --config react.yaml
```

Outputs land in `out/<owner__repo>/`:
`script.json` (MisoTTS input), `transcript.txt` (read it), `wiki.md` (DeepWiki wiki).

## Personas

Each role has 0→1 sliders that render into the agent's system preamble. Presets are starting
points; edit the YAML to taste. See `src/dev_podcast/personas.py`.

- **Student:** pace, depth, testing_appetite, assertiveness, tangents.
  Presets: `sprinter`, `completionist`, `skeptic`.
- **Teacher:** directness, conciseness, rigor, encouragement, testing_inclination.
  Presets: `socratic`, `lecturer`, `pair_programmer`.

High testing sliders insert **quiz breaks** into the script (the Teacher poses a question,
the Student answers, the Teacher evaluates) — tagged in `script.json` so audio can pause.

## Notes

- Public repos only (DeepWiki free tier). Private repos are a later add (codedb / Devin MCP).
- Design: `docs/superpowers/specs/2026-06-09-dev-podcast-design.md`.
