"""Branding for the console. Change it here and it changes everywhere."""

NAME = "LAZSTATION 2"
SHORT = "LAZSTATION"
TAGLINE = "T H E   T E R M I N A L   C O N S O L E"

#: 4-row letter blocks. Composing the logo from fixed-width glyphs keeps the
#: columns aligned -- hand-drawn ASCII drifts and shears when centred.
_GLYPHS = {
    "L": ["88    ", "88    ", "88    ", "888888"],
    "A": ["  db  ", " dPYb ", "dP__Yb", "dP''''Yb"],
    "Z": ["8888P", "  dP ", " dP  ", "8888P"],
    "S": [".d888b", "88'   ", "`8bo. ", "Y888P'"],
    "T": ["888888", "  88  ", "  88  ", "  88  "],
    "I": ["88", "88", "88", "88"],
    "O": [" dPYb ", "dP  Yb", "Yb  dP", " YbodP"],
    "N": ["88b 88", "88Yb88", "88 Y88", "88  Y8"],
    "2": ["dPYb", "  dP", " dP ", "8888"],
    " ": [" ", " ", " ", " "],
}


def _compose(text: str, gap: str = " ") -> list[str]:
    rows = ["", "", "", ""]
    for i, ch in enumerate(text.upper()):
        glyph = _GLYPHS.get(ch)
        if glyph is None:
            continue
        width = max(len(r) for r in glyph)
        for r in range(4):
            rows[r] += glyph[r].ljust(width) + (gap if i < len(text) - 1 else "")
    width = max(len(r) for r in rows)
    return [r.ljust(width) for r in rows]


LOGO_RAW = _compose("LAZSTATION")
LOGO_WITH_2 = _compose("LAZSTATION 2")

#: Small logo for the launcher header.
LOGO_SMALL = [
    "┬  ┌─┐┌─┐┌─┐┌┬┐┌─┐┌┬┐┬┌─┐┌┐┌   ┌─┐",
    "│  ├─┤┌─┘└─┐ │ ├─┤ │ ││ ││││   ┌─┘",
    "┴─┘┴ ┴└─┘└─┘ ┴ ┴ ┴ ┴ ┴└─┘┘└┘   └─┘",
]


def logo(width: int | None = None) -> list[str]:
    """Widest logo that fits, padded square so it can be centred as a block."""
    for art in (LOGO_WITH_2, LOGO_RAW, LOGO_SMALL):
        art_w = max(len(line) for line in art)
        if width is None or art_w <= width:
            return [line.ljust(art_w) for line in art]
    return [line.ljust(max(len(l) for l in LOGO_SMALL)) for line in LOGO_SMALL]
