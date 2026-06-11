# Baseline: TASEmulators/desmume — 2026-06-11

This is the FIRST desmume run, kept to measure improvement. It was generated with the
storytelling-teacher personas as they were *before* the 2026-06-11 "why / intuition" pass.

## Settings used (job 617035a5)
The studio POST sent only repo/minutes/tone/starting_point, so every slider defaulted to **0.50**:

| | value |
|---|---|
| repo | TASEmulators/desmume |
| target_minutes | 3  (← short; this is why it's only 8 turns) |
| tone | casual |
| starting_point | "I know nothing about this repo. What is the single most useful story you can tell me about how it is constructed?" |
| student: pace / depth / testing_appetite / assertiveness / tangents | 0.50 each |
| teacher: directness / conciseness / rigor / encouragement / testing_inclination | 0.50 each |

## Known problems (the feedback that drove the next changes)
- Junior up-levels too fast (sounds like the smartest student in the room; already knows
  DMA, GPU registers, etc.). Want a tunable prior-knowledge level; default slower/novice.
- Reads like a curriculum / codebase tour. Want intuition for WHY decisions were made,
  constraints at the time, alternatives rejected — so the junior could have derived it.
- Should reference outside sources (textbooks, blogs, SO/Reddit/Discord), not just DeepWiki.
- quiz_a answers get cut off (max_tokens too low).
- No fixed minutes/turns requirement — let it run until natural conclusion.

## Useful teacher phrasings to lean on
- "the engineers probably did this because…"
- "at the time the constraint was X, so they had to Y"
- "if I were explaining this to a kid who knew nothing about the subject, I'd say…"
