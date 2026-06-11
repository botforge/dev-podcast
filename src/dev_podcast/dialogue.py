"""The inner loop: two separate Claude agents converse about a repo.

Teacher  -> Claude + DeepWiki MCP connector (server-side, no local clone/GPU).
Student  -> Claude, code-blind, drives by asking.
Orchestrator -> routes turns, tracks length, injects timing nudges, stops on
                consensus/target. It NEVER writes dialogue content.

Output: script.json (MisoTTS input) + wiki.md (free DeepWiki deliverable) + transcript.txt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .personas import PodcastConfig


def _is_mcp_conn_error(e: Exception) -> bool:
    """DeepWiki dropping the connection surfaces as a 400 mentioning the MCP server."""
    return isinstance(e, anthropic.BadRequestError) and "MCP server" in str(e)

MODEL = "claude-opus-4-8"
WORDS_PER_MINUTE = 150
MCP_BETA = "mcp-client-2025-11-20"
DEEPWIKI = {"type": "url", "name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}
DEEPWIKI_TOOLS = [{"type": "mcp_toolset", "mcp_server_name": "deepwiki"}]

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


def _clean(text: str) -> str:
    """Strip em/en dashes (an LLM tell, and awkward for TTS) and tidy whitespace."""
    text = text.replace(" — ", ", ").replace("—", ", ").replace("–", "-")
    text = text.replace(" , ", ", ").replace(" ,", ",")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


class Dialogue:
    def __init__(self, config: PodcastConfig, client: anthropic.Anthropic | None = None,
                 on_turn=None):
        self.cfg = config
        self.client = client or anthropic.Anthropic()
        self.on_turn = on_turn  # optional callback(Turn) -- used to stream turns to a UI
        self.turns: list[Turn] = []
        # Mirrored histories: each agent sees its own turns as "assistant",
        # the other agent's as "user".
        self.teacher_msgs: list[dict] = []
        self.student_msgs: list[dict] = []

    # --- resilient API wrapper -----------------------------------------------

    def _beta_create(self, *, retries: int = 3, **kw):
        """beta.messages.create, retrying transient DeepWiki connection drops."""
        last: Exception | None = None
        for i in range(retries):
            try:
                return self.client.beta.messages.create(**kw)
            except anthropic.BadRequestError as e:
                if not _is_mcp_conn_error(e):
                    raise
                last = e
                time.sleep(2 * (i + 1))
        assert last is not None
        raise last

    # --- knowledge seed + wiki deliverable (one DeepWiki call each) -----------

    def _ask_deepwiki(self, question: str, max_tokens: int = 4000) -> str:
        kw = dict(
            model=MODEL, max_tokens=max_tokens, betas=[MCP_BETA],
            mcp_servers=[DEEPWIKI], tools=DEEPWIKI_TOOLS,
            system=(
                f"You can query the DeepWiki knowledge tool for the GitHub repository "
                f"`{self.cfg.repo}`. Use it to answer grounded in the real code."
            ),
            messages=[{"role": "user", "content": question}],
        )
        resp = self._beta_create(**kw)
        while resp.stop_reason == "pause_turn":
            kw["messages"] = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": resp.content},
            ]
            resp = self._beta_create(**kw)
        return _text_of(resp.content)

    def build_seed_and_wiki(self) -> tuple[str, str]:
        try:
            seed = self._ask_deepwiki(
                "In 2-3 sentences, give a newcomer the high-level pitch of this repo: what "
                "it is, what problem it solves, and the single most interesting thing about "
                "how it's built. Plain prose, no headings.",
                max_tokens=1000,
            )
        except anthropic.APIError:
            seed = ""
        try:
            wiki = self._ask_deepwiki(
                "Produce a concise markdown wiki of this repo for an engineer: an "
                "architecture overview, the key modules and what each does, and the 2-3 "
                "most important runtime flows. Use headings and bullet points.",
                max_tokens=6000,
            )
        except anthropic.APIError:
            wiki = ""  # best-effort deliverable; don't sink the whole episode
        return seed, wiki

    # --- the two agents -------------------------------------------------------

    def _student_turn(self, director: str | None, segment: str) -> Turn:
        msgs = list(self.student_msgs)
        if director:
            msgs.append({"role": "user", "content": f"[director note, not spoken: {director}]"})
        resp = self.client.messages.create(
            model=MODEL,
            max_tokens=350,  # a turn is 1-3 sentences, not an essay
            thinking={"type": "disabled"},  # curiosity, not deep reasoning -- keep it snappy
            system=self.cfg.student.preamble(self.cfg.repo, self._seed, self.cfg.episode.tone),
            messages=msgs,
        )
        text = _text_of(resp.content)
        self._record(STUDENT, text, segment)
        return self.turns[-1]

    def _teacher_turn(self, director: str | None, segment: str, max_tokens: int = 450) -> Turn:
        msgs = list(self.teacher_msgs)
        if director:
            msgs.append({"role": "user", "content": f"[director note, not spoken: {director}]"})
        system = self.cfg.teacher.preamble(self.cfg.repo, self.cfg.episode.tone)
        common = dict(model=MODEL, max_tokens=max_tokens, thinking={"type": "adaptive"},
                      output_config={"effort": "medium"}, system=system)
        try:
            resp = self._beta_create(betas=[MCP_BETA], mcp_servers=[DEEPWIKI],
                                     tools=DEEPWIKI_TOOLS, messages=msgs, **common)
            while resp.stop_reason == "pause_turn":
                msgs.append({"role": "assistant", "content": resp.content})
                resp = self._beta_create(betas=[MCP_BETA], mcp_servers=[DEEPWIKI],
                                         tools=DEEPWIKI_TOOLS, messages=msgs, **common)
        except anthropic.APIError:
            # DeepWiki unavailable -> let the senior answer from the conversation so far.
            resp = self.client.messages.create(messages=msgs, **common)
        text = _text_of(resp.content)
        self._record(TEACHER, text, segment)
        return self.turns[-1]

    def _record(self, speaker_id: int, text: str, segment: str) -> None:
        text = _clean(text)
        turn = Turn(speaker_id, text, segment)
        self.turns.append(turn)
        # Append to both histories as plain text (we don't re-send MCP tool blocks).
        if speaker_id == TEACHER:
            self.teacher_msgs.append({"role": "assistant", "content": text})
            self.student_msgs.append({"role": "user", "content": text})
        else:
            self.student_msgs.append({"role": "assistant", "content": text})
            self.teacher_msgs.append({"role": "user", "content": text})
        if self.on_turn:
            self.on_turn(turn)

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
        # Student re-explains the context a couple of times across the episode.
        n_recaps = 2
        recap_marks = [round(target_words * (i + 1) / (n_recaps + 1)) for i in range(n_recaps)]

        # 1) Student opens with the configured starting point.
        sp = self.cfg.episode.starting_point
        self.student_msgs.append({"role": "user", "content": (
            "[director note, not spoken: you're live. Open the episode by asking, in your "
            f"own natural voice, essentially this: \"{sp}\"]"
        )})
        self._student_turn(director=None, segment="open")

        # 2) Teacher opens with a short storytelling lecture (~1 min) from first principles.
        self._teacher_turn(
            director="this is the OPENING. Explain the shit about this repo as a short story "
                     "from first principles, 3Blue1Brown / Khan Academy style. Take up to "
                     "about a minute (~130 words): what it is, why it exists, and the single "
                     "most useful story of how it's built. Then we go into back-and-forth.",
            segment="story", max_tokens=700,
        )

        # 3) Back-and-forth, with periodic quiz + student-recap checkpoints.
        next_speaker = STUDENT
        while True:
            wc = self._word_count

            if wc >= target_words and next_speaker == STUDENT:
                self._student_turn(director="re-explain the whole thing back in your own words, then say what finally clicked.", segment="recap")
                self._teacher_turn(director="confirm or correct the recap, then bring the episode to a natural close and sign off.", segment="close")
                break

            if recap_marks and wc >= recap_marks[0] and next_speaker == STUDENT:
                recap_marks.pop(0)
                self._student_turn(director="pause and re-explain, in your own words, what you understand so far; check your mental model and invite correction.", segment="recap")
                next_speaker = TEACHER
                continue

            if quiz_marks and wc >= quiz_marks[0] and next_speaker == TEACHER:
                quiz_marks.pop(0)
                self._teacher_turn(director="pose ONE short question to test the junior's understanding so far, then wait.", segment="quiz_q")
                self._student_turn(director="answer the senior's quiz question; attempt it for real.", segment="quiz_a")
                self._teacher_turn(director="evaluate the answer in 1-2 sentences, then move on.", segment="quiz_eval")
                next_speaker = STUDENT
                continue

            note = ("we're near time -- start steering toward a wrap-up and consensus."
                    if wc >= 0.85 * target_words else None)
            if next_speaker == STUDENT:
                self._student_turn(director=note, segment="dialogue")
                next_speaker = TEACHER
            else:
                self._teacher_turn(director=note, segment="dialogue")
                next_speaker = STUDENT

        return self.turns

    # --- output ---------------------------------------------------------------

    def save(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        script = {
            "repo": self.cfg.repo,
            "target_minutes": self.cfg.episode.target_minutes,
            "turns": [t.__dict__ for t in self.turns],
        }
        (out_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False))
        (out_dir / "wiki.md").write_text(getattr(self, "_wiki", ""))
        transcript = "\n\n".join(
            f"{'SENIOR' if t.speaker_id == TEACHER else 'JUNIOR'}"
            f"{'' if t.segment_type == 'dialogue' else f' [{t.segment_type}]'}: {t.text}"
            for t in self.turns
        )
        (out_dir / "transcript.txt").write_text(transcript)
