# Dev Podcast — Design Spec

**Date:** 2026-06-09
**Status:** Approved (verbal), inner loop in build

## One-line

Point at a public GitHub repo and a persona config → generate a genuine 15–20 minute
two-voice podcast where a senior dev (Teacher) and a junior dev (Student) converse and
reach shared understanding → render to audio with MisoTTS 8B.

## Hard constraints (from the user, non-negotiable)

1. **No single writer.** The dialogue is two *separate* Claude agents with *narrow,
   different* context. The Teacher's only base context is a preamble; it then responds to
   whatever the Student asks. The orchestrator routes turns and stops the conversation — it
   **never generates dialogue content**. The transcript is literally the byte-stream of two
   independent agents talking.
2. **As little done locally as possible; the model never runs locally.** MisoTTS (8B,
   needs 24 GB+ VRAM) runs on RunPod, never on the user's machine.
3. **Fast local iteration.** The script (the creative surface) is tuned in a tight local
   loop that is pure Claude API calls — no GPU, no model, sub-minute, cents per run.

## Two-loop architecture

```
INNER LOOP  (local, fast, no GPU — where you iterate)
  repo (org/repo) + persona config
      → Teacher agent  (Claude + DeepWiki MCP connector, server-side)
      ⇄ Student agent  (Claude, code-blind)
      → orchestrator routes turns, tracks length, stops on consensus/target
      → script.json   =  [{speaker_id, text, segment_type}, ...]   (MisoTTS input)
      → wiki.md       (fetched from DeepWiki — a free deliverable)

OUTER LOOP  (RunPod Serverless GPU — called only when a script is worth hearing)
  script.json --HTTPS--> MisoTTS 8B endpoint --> full_conversation.wav --> R2 --> URL
```

Each stage writes a file the next stage reads, so any stage can be re-run and inspected
alone ("pipe-flush but inspectable").

## Knowledge layer: DeepWiki MCP

- The Teacher's "expert knowledge" is the hosted **DeepWiki MCP** server
  (`https://mcp.deepwiki.com/mcp`) — free, no auth, **public repos only**.
- Tools: `read_wiki_structure`, `read_wiki_contents` (→ our `wiki.md` deliverable),
  `ask_question` (semantic, grounded Q&A — the Teacher's recall).
- Reached via Anthropic's **MCP connector** (`mcp_servers` param on the Messages API,
  beta header `mcp-client-2025-11-20`). Claude does the DeepWiki round-trips server-side;
  our local code makes a normal API call. Nothing indexed or cloned locally.
- Private-repo support is out of scope for v1 (would need codedb local or Devin's paid MCP).

## The two agents

| | Teacher (speaker_id 0) | Student (speaker_id 1) |
|---|---|---|
| Base context | persona preamble only | persona preamble only |
| Sees | Student's latest msg + running dialogue | running dialogue + thin seed (repo name + wiki intro) |
| Tools | DeepWiki MCP (`ask_question`, etc.) | **none** — code-blind, drives by asking |
| Role in transcript | answers precisely from the graph | probes from first principles toward understanding |

Separate Claude conversations with mirrored roles (each agent's own turns are `assistant`,
the other's are `user`). The orchestrator owns both message lists and the merged transcript.

## Personas: 0→1 sliders → preamble + behavior

A persona config sets sliders per role; presets are named bundles ("your learning style");
the user tunes from there.

**Student sliders:** pace, depth, testing_appetite, assertiveness, tangents.
**Teacher sliders:** directness, conciseness, rigor, encouragement, testing_inclination.
**Episode:** target_minutes, tone (casual↔formal).

Each slider maps through thresholds to a line of preamble text. Sliders change *who the
agents are*, never collapse them into one writer.

### Test breaks (the one slider that changes structure)

When testing appetite/inclination is high, the orchestrator injects a **timing nudge**
(not content) into the Teacher's turn: "a check-in would fit here." The Teacher *generates*
the quiz question, the Student answers, the Teacher evaluates. These turns carry a tag:

```json
{ "speaker_id": 0, "text": "...", "segment_type": "quiz_q" }
{ "speaker_id": 1, "text": "...", "segment_type": "quiz_a" }
{ "speaker_id": 0, "text": "...", "segment_type": "quiz_eval" }
```

Audio renders them as normal speech (optional short pause before a quiz). The orchestrator
signals only *timing* — "no single writer" holds.

## script.json contract (the seam between loops)

```json
{
  "repo": "owner/name",
  "target_minutes": 18,
  "turns": [
    { "speaker_id": 0, "text": "...", "segment_type": "dialogue" },
    { "speaker_id": 1, "text": "...", "segment_type": "dialogue" }
  ]
}
```

`speaker_id`: 0 = Teacher/senior, 1 = Student/junior — matches MisoTTS's `speaker=0|1`.
`segment_type` ∈ `dialogue | quiz_q | quiz_a | quiz_eval | open | close`.

## MisoTTS (outer loop) — known facts

- 8B backbone + 300M decoder, ~16 GB bf16, needs 24 GB+ VRAM (RTX 4090 / A5000 / L4).
- Input is already a multi-speaker turn list (`{text, speaker_id}`); generates each turn,
  concatenates to one WAV via `torchaudio.save`. English only.
- Voice identity from speaker IDs 0/1, optionally primed with a short reference clip per
  speaker (voice cloning) so senior/junior sound distinct and consistent.
- **Context windowing risk:** the reference script accumulates *all* prior audio as context,
  which won't survive 20 minutes (memory/time blow-up). We window to the last N turns.
- Deployed as a **RunPod Serverless** endpoint (scales to zero, weights baked into the image
  or on a network volume to avoid re-download). Output WAV uploaded to Cloudflare R2.

## Models

- Both agents: `claude-opus-4-8` (adaptive thinking available; effort tunable per role).
- Teacher leans higher effort (it reasons over the graph); Student stays light/curious.

## Build order

1. **Inner loop** (this milestone): personas → two-agent dialogue via DeepWiki MCP →
   `script.json` + `wiki.md`. Tune until conversations are genuinely good.
2. **Outer loop**: RunPod Serverless MisoTTS endpoint, `script.json` → WAV → R2.

## Out of scope (v1, YAGNI)

- Private repos; non-English; a visual graph browser (DeepWiki's website covers "surfing");
  speaker diarization beyond two voices; live/streaming generation.
