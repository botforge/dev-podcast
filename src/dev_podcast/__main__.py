"""CLI for the inner loop.

  dev-podcast <owner/repo> [--student PRESET] [--teacher PRESET] [--minutes N]
  dev-podcast <owner/repo> --config my.yaml
  dev-podcast --write-config my.yaml <owner/repo>   # dump an editable config and exit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .dialogue import Dialogue
from .personas import STUDENT_PRESETS, TEACHER_PRESETS, PodcastConfig, preset_config


def _slug(repo: str) -> str:
    return repo.replace("/", "__")


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="dev-podcast")
    p.add_argument("repo", help="public GitHub repo as owner/name")
    p.add_argument("--student", choices=list(STUDENT_PRESETS), default="completionist")
    p.add_argument("--teacher", choices=list(TEACHER_PRESETS), default="pair_programmer")
    p.add_argument("--minutes", type=int, default=18)
    p.add_argument("--config", type=Path, help="load a persona YAML (overrides presets)")
    p.add_argument("--write-config", type=Path, help="write an editable config YAML and exit")
    p.add_argument("--out", type=Path, default=Path("out"))
    args = p.parse_args()

    if args.config:
        cfg = PodcastConfig.from_yaml(args.config.read_text())
        cfg.repo = args.repo
    else:
        cfg = preset_config(args.repo, student=args.student, teacher=args.teacher)
    cfg.episode.target_minutes = args.minutes

    if args.write_config:
        args.write_config.write_text(cfg.to_yaml())
        print(f"Wrote {args.write_config} -- edit the sliders and rerun with --config.")
        return 0

    out_dir = args.out / _slug(args.repo)
    print(f"Repo:    {cfg.repo}")
    print(f"Student: {args.student}   Teacher: {args.teacher}   Target: {args.minutes} min")
    print("Querying DeepWiki + running the conversation (this takes a few minutes)...\n")

    dlg = Dialogue(cfg)
    turns = dlg.run()
    dlg.save(out_dir)

    words = sum(len(t.text.split()) for t in turns)
    print(f"Done. {len(turns)} turns, ~{words} words (~{words // 150} min).")
    print(f"  {out_dir/'script.json'}    <- feed this to MisoTTS")
    print(f"  {out_dir/'transcript.txt'} <- read it")
    print(f"  {out_dir/'wiki.md'}        <- DeepWiki wiki")
    return 0


if __name__ == "__main__":
    sys.exit(main())
