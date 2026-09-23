"""`ts new <slug>` -- generate a working game from a template."""
from __future__ import annotations

import re
from pathlib import Path

from . import paths

MANIFEST = '''[game]
name = "{title}"
slug = "{slug}"
version = "0.1.0"
author = "{author}"
description = """
{title} -- a TermStation game.

Edit games/{slug}/main.py and this description, then press r in the
console to see your changes."""
tags = [{tags}]
entry = ["{{python}}", "main.py"]
min_cols = 80
min_rows = 24
'''

MAIN = '''#!/usr/bin/env python3
"""{title} -- a TermStation game."""
import sys

import termstation_sdk as ts


def main() -> int:
    save = ts.load({{"plays": 0, "best": 0}})
    save["plays"] += 1

    ts.clear()
    print(ts.title("{title}"))
    print()
    print(f"  welcome back, {{ts.profile()}} -- visit #{{save['plays']}}")
    print()

    while True:
        choice = ts.menu("What now?", ["Play a round", "Show stats"], back="Quit")
        if choice == -1:
            break
        if choice == 0:
            score = ts.ask_int("pick a number 1-100", 1, 100)
            save["best"] = max(save["best"], score)
            print(ts.color(f"  scored {{score}}!", "bright_green"))
        elif choice == 1:
            print(ts.box([
                f" plays : {{save['plays']}}",
                f" best  : {{save['best']}}",
            ]))
        ts.pause()

    ts.save(save)
    print(ts.color("\\n  saved. see you on the station.\\n", "cyan"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
'''


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def titleize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w)


def create(name: str, target: Path | None = None, author: str = "",
           tags: list[str] | None = None) -> Path:
    slug = slugify(name)
    base = target or paths.BUNDLED_GAMES
    directory = base / slug
    if directory.exists():
        raise FileExistsError(f"{directory} already exists")

    title = titleize(slug)
    directory.mkdir(parents=True)
    tag_list = ", ".join(f'"{t}"' for t in (tags or ["wip"]))
    (directory / "game.toml").write_text(
        MANIFEST.format(title=title, slug=slug, author=author, tags=tag_list),
        encoding="utf-8")
    main = directory / "main.py"
    main.write_text(MAIN.format(title=title), encoding="utf-8")
    main.chmod(0o755)
    return directory
