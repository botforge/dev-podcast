"""The inner loop: two separate Claude agents converse about a repo.

Teacher  -> Claude + DeepWiki MCP connector (server-side, no local clone/GPU).
Student  -> Claude, code-blind, drives by asking.
Orchestrator -> routes turns, tracks length, injects timing nudges, stops on
                consensus/target. It NEVER writes dialogue content.

Output: script.json (MisoTTS input) + wiki.md (free DeepWiki deliverable) + transcript.txt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .personas import PodcastConfig

MODEL = "claude-opus-4-8"
WORDS_PER_MINUTE = 150
MCP_BETA = "mcp-client-2025-11-20"
DEEPWIKI = {"type": "url", "name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}

TEACHER = 0  # speaker_id -- senior
STUDENT = 1  # speaker_id -- junior


@dataclass
class Turn:
    speaker_id: int
    text: str
    segment_type: str = "dialogue"


def _text_of(content) -> str:
    """Join the text blocks of a response, ignoring server-side MCP tool blocks."""
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


class Dialogue:
    def __init__(self, config: PodcastConfig, client: anthropic.Anthropic | None = None):
        self.cfg = config
        self.client = client or anthropic.Anthropic()
        self.turns: list[Turn] = []
        # Mirrored histories: each agent sees its own turns as "assistant",
        # the other agent's as "user".
        self.teacher_msgs: list[dict] = []
        self.student_msgs: list[dict] = []

    # --- knowledge seed + wiki deliverable (one DeepWiki call each) -----------

    def _ask_deepwiki(self, question: str, max_tokens: int = 4000) -> str:
        resp = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            betas=[MCP_BETA],
            mcp_servers=[DEEPWIKI],
            system=(
                f"You can query the DeepWiki knowledge tool for the GitHub repository "
                f"`{self.cfg.repo}`. Use it to answer grounded in the real code."
            ),
            messages=[{"role": "user", "content": question}],
        )
        # Server-side tools may pause; resume until done.
        while resp.stop_reason == "pause_turn":
            resp = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                betas=[MCP_BETA],
                mcp_servers=[DEEPWIKI],
                messages=[
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": resp.content},
                ],
            )
        return _text_of(resp.content)

    def build_seed_and_wiki(self) -> tuple[str, str]:
        seed = self._ask_deepwiki(
            "In 2-3 sentences, give a newcomer the high-level pitch of this repo: what it "
            "is, what problem it solves, and the single most interesting thing about how "
            "it's built. Plain prose, no headings.",
            max_tokens=1000,
        )
        wiki = self._ask_deepwiki(
            "Produce a concise markdown wiki of this repo for an engineer: an architecture "
            "overview, the key modules and what each does, and the 2-3 most important "
            "runtime flows. Use headings and bullet points.",
            max_tokens=6000,
        )
        return seed, wiki

    # --- the two agents -------------------------------------------------------

    def _student_turn(self, director: str | None, segment: str) -> Turn:
        msgs = list(self.student_msgs)
        if director:
            msgs.append({"role": "user", "content": f"[director note, not spoken: {director}]"})
        resp = self.client.messages.create(
            model=MODEL,
            max_tokens=1200,
            thinking={"type": "disabled"},  # curiosity, not deep reasoning -- keep it snappy
            system=self.cfg.student.preamble(self.cfg.repo, self._seed, self.cfg.episode.tone),
            messages=msgs,
        )
        text = _text_of(resp.content)
        self._record(STUDENT, text, segment)
        return self.turns[-1]

    def _teacher_turn(self, director: str | None, segment: str) -> Turn:
        msgs = list(self.teacher_msgs)
        if director:
            msgs.append({"role": "user", "content": f"[director note, not spoken: {director}]"})
        resp = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=1500,
            betas=[MCP_BETA],
            mcp_servers=[DEEPWIKI],
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=self.cfg.teacher.preamble(self.cfg.repo, self.cfg.episode.tone),
            messages=msgs,
        )
        while resp.stop_reason == "pause_turn":
            msgs.append({"role": "assistant", "content": resp.content})
            resp = self.client.beta.messages.create(
                model=MODEL, max_tokens=1500, betas=[MCP_BETA], mcp_servers=[DEEPWIKI],
                thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                system=self.cfg.teacher.preamble(self.cfg.repo, self.cfg.episode.tone),
                messages=msgs,
            )
        text = _text_of(resp.content)
        self._record(TEACHER, text, segment)
        return self.turns[-1]

    def _record(self, speaker_id: int, text: str, segment: str) -> None:
        self.turns.append(Turn(speaker_id, text, segment))
        # Append to both histories as plain text (we don't re-send MCP tool blocks).
        if speaker_id == TEACHER:
            self.teacher_msgs.append({"role": "assistant", "content": text})
            self.student_msgs.append({"role": "user", "content": text})
        else:
            self.student_msgs.append({"role": "assistant", "content": text})
            self.teacher_msgs.append({"role": "user", "content": text})

    # --- orchestration (routing + length + nudges only; no content) ----------

    @property
    def _word_count(self) -> int:
        return sum(len(t.text.split()) for t in self.turns)

    def run(self) -> list[Turn]:
        self._seed, self._wiki = self.build_seed_and_wiki()

        target_words = self.cfg.episode.target_minutes * WORDS_PER_MINUTE
        testing = max(self.cfg.teacher.testing_inclination, self.cfg.student.testing_appetite)
        n_quizzes = round(testing * 3)  # 0..3 check-ins across the episode
        quiz_marks = (
            [round(target_words * (i + 1) / (n_quizzes + 1)) for i in range(n_quizzes)]
            if n_quizzes else []
        )

        # Student opens (drives). Prime its history with a kickoff director note.
        self.student_msgs.append({"role": "user", "content": (
            "[director note, not spoken: you're live. Open the episode -- introduce what "
            "you're here to understand and ask your first real question.]"
        )})
        self._student_turn(director=None, segment="open")
        self._teacher_turn(director=None, segment="dialogue")

        while True:
            wc = self._word_count
            if quiz_marks and wc >= quiz_marks[0]:
                quiz_marks.pop(0)
                self._teacher_turn(
                    director="a check-in would fit here -- pose ONE short question to test "
                             "the junior's understanding so far, then wait for the answer.",
                    segment="quiz_q",
                )
                self._student_turn(director="answer the senior's quiz question; attempt it for real.", segment="quiz_a")
                self._teacher_turn(director="briefly evaluate the answer, then move on.", segment="quiz_eval")
                continue

            if wc >= target_words:
                self._student_turn(director="you've reached real understanding -- summarize what clicked.", segment="dialogue")
                self._teacher_turn(director="bring the episode to a natural close and sign off.", segment="close")
                break

            near_end = wc >= 0.85 * target_words
            note = "we're near time -- start steering toward a wrap-up and consensus." if near_end else None
            self._student_turn(director=note, segment="dialogue")
            self._teacher_turn(director=note, segment="dialogue")

        return self.turns

    # --- output ---------------------------------------------------------------

    def save(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        script = {
            "repo": self.cfg.repo,
            "target_minutes": self.cfg.episode.target_minutes,
            "turns": [t.__dict__ for t in self.turns],
        }
        (out_dir / "script.json").write_text(json.dumps(script, indent=2))
        (out_dir / "wiki.md").write_text(getattr(self, "_wiki", ""))
        transcript = "\n\n".join(
            f"{'SENIOR' if t.speaker_id == TEACHER else 'JUNIOR'}"
            f"{'' if t.segment_type == 'dialogue' else f' [{t.segment_type}]'}: {t.text}"
            for t in self.turns
        )
        (out_dir / "transcript.txt").write_text(transcript)
