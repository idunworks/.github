"""Guard projects.json against cards that disappear by accident.

idunworks.com/projects is built from projects.json. Several people and tools edit it, and an edit made
from an old copy can silently drop someone else's card (it happened on 2026-11-16). This script compares
the file before and after a push:

- a card whose slug is gone is put back where it was, unless a commit in the push says
  `remove-card: <slug>`;
- the file must stay valid JSON with a "projects" list, or the site would show no cards at all.

Usage: guard_projects.py <before-sha> <after-sha>   (run from the repository root)
Exit codes: 0 nothing to do, 1 cards were restored (file rewritten), 2 the file is broken.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

FILE = "projects.json"
NULL_SHA = "0" * 40
REMOVE_MARKER = re.compile(r"remove-card:\s*([a-z0-9][a-z0-9-]*)", re.IGNORECASE)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def load_at(sha: str) -> dict | None:
    """The parsed file at a commit, or None if it didn't exist there."""
    try:
        return json.loads(git("show", f"{sha}:{FILE}"))
    except subprocess.CalledProcessError:
        return None


def slugs(data: dict) -> list[str]:
    return [p.get("slug") for p in data.get("projects", []) if isinstance(p, dict)]


def allowed_removals(before: str, after: str) -> set[str]:
    messages = git("log", "--format=%B", f"{before}..{after}")
    return {m.lower() for m in REMOVE_MARKER.findall(messages)}


def restore(old: dict, new: dict, missing: set[str]) -> dict:
    """Put each missing card back after the card that preceded it in the old file."""
    projects = list(new["projects"])
    old_list = old["projects"]
    for i, card in enumerate(old_list):
        if card.get("slug") not in missing:
            continue
        current = [p.get("slug") for p in projects]
        earlier = [p.get("slug") for p in old_list[:i] if p.get("slug") in current]
        at = current.index(earlier[-1]) + 1 if earlier else 0
        projects = [*projects[:at], card, *projects[at:]]
    return {**new, "projects": projects}


def main(before: str, after: str) -> int:
    try:
        new = json.loads(Path(FILE).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error file={FILE}::{FILE} is not valid JSON ({exc}); the projects page would be empty")
        return 2
    if not isinstance(new, dict) or not isinstance(new.get("projects"), list):
        print(f'::error file={FILE}::{FILE} must be an object with a "projects" list')
        return 2

    old = None if before == NULL_SHA else load_at(before)
    if old is None:
        print("No earlier version to compare with; nothing to guard.")
        return 0

    missing = set(slugs(old)) - set(slugs(new)) - allowed_removals(before, after)
    if not missing:
        print(f"OK: {len(slugs(new))} cards, none dropped.")
        return 0

    fixed = restore(old, new, missing)
    Path(FILE).write_text(json.dumps(fixed, indent="\t", ensure_ascii=False) + "\n")
    names = ", ".join(sorted(missing))
    print(f"::error file={FILE}::Card(s) dropped without 'remove-card: <slug>' in the commit message: {names}. "
          "Restored them. To remove a card on purpose, say so in the commit message.")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
