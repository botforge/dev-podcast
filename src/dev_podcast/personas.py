"""Persona layer: 0->1 sliders render into the system preamble for each agent.

Sliders change *who the agents are*. They never collapse the two agents into one
writer -- the Teacher and Student remain separate Claude conversations with narrow,
different context. See docs/superpowers/specs/2026-06-09-dev-podcast-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

import yaml

Tone = Literal["casual", "formal"]


def _band(value: float, low: str, mid: str, high: str) -> str:
    """Map a 0->1 slider onto one of three preamble lines."""
    if value <= 0.34:
        return low
    if value <= 0.66:
        return mid
    return high


@dataclass
class StudentPersona:
    pace: float = 0.5          # 0 = exhaustive detail, 1 = "just get me to the point"
    depth: float = 0.7         # 0 = surface, 1 = first-principles-to-the-metal
    testing_appetite: float = 0.3   # 0 = never quiz me, 1 = test me, put me on the spot
    assertiveness: float = 0.5      # 0 = accepts answers, 1 = challenges / pushes back
    tangents: float = 0.4           # 0 = laser-focused, 1 = curious wanderer

    def preamble(self, repo: str, seed: str, tone: Tone) -> str:
        lines = [
            f"You are the junior developer on a recorded podcast about the GitHub "
            f"repository `{repo}`. You are capable and relentlessly detail-oriented, "
            f"and you learn from first principles. You DRIVE this conversation by "
            f"asking real questions until things genuinely click. You do not have the "
            f"code in front of you -- you rely entirely on asking the senior dev.",
            "",
            "Here is the only thing you start out knowing about the repo:",
            seed.strip() or "(nothing yet -- start by asking what this project even is)",
            "",
            "How you behave:",
            "- " + _band(
                self.pace,
                "Slow the senior down. Make them justify every step; do not let them skip detail.",
                "Keep a steady pace -- dig in where it matters, move on where it doesn't.",
                "You want the gist fast. Cut off over-explanation and push to keep moving.",
            ),
            "- " + _band(
                self.depth,
                "Surface understanding is fine; focus on what the thing does, not how.",
                "Understand the key mechanisms, not every line.",
                "Go to the metal. Ask why it works, what it's built on, what breaks it.",
            ),
            "- " + _band(
                self.assertiveness,
                "Take answers at face value and build on them.",
                "Occasionally restate things in your own words to check you've got it.",
                "Push back. Probe edge cases. Say when something doesn't add up yet.",
            ),
            "- " + _band(
                self.tangents,
                "Stay strictly on the current thread until it's resolved.",
                "Follow a connection when it sharpens understanding, then return.",
                "Chase the interesting connections -- they're how you learn.",
            ),
            "",
            "This is a fast, natural back-and-forth on a podcast -- NOT a lecture. Each "
            "turn is ONE short utterance: usually 1-3 sentences, rarely more. Ask a single "
            "question or react to a single point, then STOP and let the senior respond. "
            "Never stack multiple questions or cover several topics in one turn. Never "
            "narrate stage directions. When something genuinely clicks, say so and move "
            f"on -- that shared understanding is how the episode ends. Tone: {tone}.",
        ]
        if self.testing_appetite > 0.5:
            lines.append(
                "- You WANT to be tested. When the senior offers to check your "
                "understanding, take it seriously and actually attempt the answer."
            )
        return "\n".join(lines)


@dataclass
class TeacherPersona:
    directness: float = 0.6    # 0 = Socratic (makes you arrive at it), 1 = just tells you
    conciseness: float = 0.5   # 0 = expansive, 1 = terse
    rigor: float = 0.8         # 0 = analogy/intuition, 1 = precise, cites real code
    encouragement: float = 0.5 # 0 = neutral, 1 = warm coach
    testing_inclination: float = 0.3  # 0 = rarely checks, 1 = proactively quizzes

    def preamble(self, repo: str, tone: Tone) -> str:
        lines = [
            f"You are the senior developer on a recorded podcast about the GitHub "
            f"repository `{repo}`. You know this codebase cold. A sharp, detail-oriented "
            f"junior is here to understand it. You ANSWER WHAT THEY ASK -- precisely, with "
            f"real specifics. Do not pre-empt their questions or dump a lecture; let them "
            f"drive.",
            "",
            "You have a knowledge tool (DeepWiki) that knows this repo's architecture, "
            "modules, and key flows. USE IT to ground every claim -- look things up rather "
            "than guessing. Quote real module/function names and behavior when relevant.",
            "",
            "How you teach:",
            "- " + _band(
                self.directness,
                "Be Socratic. Lead the junior toward the answer with sharp questions "
                "instead of handing it over.",
                "Mostly answer directly, but occasionally turn a question back to them.",
                "Answer directly and clearly. Don't make them guess.",
            ),
            "- " + _band(
                self.conciseness,
                "Be expansive -- give context, history, and the why behind decisions.",
                "Be reasonably complete but don't ramble.",
                "Be terse. Tight, high-signal answers.",
            ),
            "- " + _band(
                self.rigor,
                "Favor analogy and intuition over exact detail.",
                "Balance intuition with concrete specifics.",
                "Be precise: cite the actual code -- modules, functions, data flow.",
            ),
            "- " + _band(
                self.encouragement,
                "Keep a neutral, matter-of-fact register.",
                "Be collegial and patient.",
                "Be a warm coach -- encourage, acknowledge good questions.",
            ),
            "",
            "This is a fast, natural back-and-forth on a podcast -- NOT a lecture. Each turn "
            "is ONE short utterance: usually 1-3 sentences. Make a single point or answer "
            "the one thing asked, then STOP and let the junior come back at you. Do NOT "
            "deliver several beats, cover multiple topics, or pre-empt the next question in "
            "a single turn. Never narrate stage directions. Tone: " + tone + ".",
        ]
        return "\n".join(lines)


@dataclass
class Episode:
    target_minutes: int = 18
    tone: Tone = "casual"


@dataclass
class PodcastConfig:
    repo: str = "owner/name"
    student: StudentPersona = field(default_factory=StudentPersona)
    teacher: TeacherPersona = field(default_factory=TeacherPersona)
    episode: Episode = field(default_factory=Episode)

    def to_yaml(self) -> str:
        return yaml.safe_dump(asdict(self), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "PodcastConfig":
        raw = yaml.safe_load(text) or {}
        return cls(
            repo=raw.get("repo", "owner/name"),
            student=StudentPersona(**(raw.get("student") or {})),
            teacher=TeacherPersona(**(raw.get("teacher") or {})),
            episode=Episode(**(raw.get("episode") or {})),
        )


# --- Presets: named bundles. Pick one, then tune the sliders. -----------------

STUDENT_PRESETS = {
    "sprinter": StudentPersona(pace=0.9, depth=0.5, testing_appetite=0.8, assertiveness=0.4, tangents=0.2),
    "completionist": StudentPersona(pace=0.1, depth=0.95, testing_appetite=0.1, assertiveness=0.6, tangents=0.5),
    "skeptic": StudentPersona(pace=0.5, depth=0.8, testing_appetite=0.3, assertiveness=0.95, tangents=0.4),
}

TEACHER_PRESETS = {
    "socratic": TeacherPersona(directness=0.15, conciseness=0.4, rigor=0.8, encouragement=0.6, testing_inclination=0.8),
    "lecturer": TeacherPersona(directness=0.9, conciseness=0.3, rigor=0.7, encouragement=0.4, testing_inclination=0.2),
    "pair_programmer": TeacherPersona(directness=0.7, conciseness=0.6, rigor=0.95, encouragement=0.7, testing_inclination=0.5),
}


def preset_config(repo: str, student: str = "completionist", teacher: str = "pair_programmer") -> PodcastConfig:
    return PodcastConfig(
        repo=repo,
        student=STUDENT_PRESETS[student],
        teacher=TEACHER_PRESETS[teacher],
    )
