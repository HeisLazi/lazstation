"""Small, optional curses UI helpers for TermStation games.

This module deliberately stops at presentation and navigation primitives.
Games still own their rules, state, and screen flow. All coordinates are local
to the curses window returned by ``termstation_sdk.tv_curses``.

    import curses
    import termstation_ui as ui

    win, screen = ts.tv_curses(stdscr, "Squad")
    body = ui.Rect(0, 0, screen.width, screen.height - 1)
    table = ui.TableView(["Name", "POS", "FIT"], rows)
    table.draw(win, body)
    key = win.getch()
    chosen = table.handle(key, body.height)

The widgets assume one terminal cell per displayed character. Pass curses
attributes to drawing methods so a game can keep its own palette and theme.
"""
from __future__ import annotations

import curses
import textwrap
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "Rect", "split_horizontal", "split_vertical", "clip", "wrap_text",
    "draw_text", "draw_rule", "draw_panel", "key_action", "Viewport",
    "ListView", "TableView", "Tabs",
]


@dataclass(frozen=True)
class Rect:
    """A rectangle in window-local terminal cells."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + max(0, self.width)

    @property
    def bottom(self) -> int:
        return self.y + max(0, self.height)

    def inset(self, amount: int = 1) -> "Rect":
        amount = max(0, amount)
        return Rect(self.x + amount, self.y + amount,
                    max(0, self.width - amount * 2),
                    max(0, self.height - amount * 2))


def split_horizontal(rect: Rect, ratio: float = 0.5,
                     gap: int = 1) -> tuple[Rect, Rect]:
    """Split a rectangle into left and right panes, clamped to its width."""
    gap = min(max(0, gap), max(0, rect.width))
    usable = max(0, rect.width - gap)
    ratio = min(1.0, max(0.0, ratio))
    left_width = int(round(usable * ratio))
    right_width = usable - left_width
    return (Rect(rect.x, rect.y, left_width, rect.height),
            Rect(rect.x + left_width + gap, rect.y, right_width, rect.height))


def split_vertical(rect: Rect, ratio: float = 0.5,
                   gap: int = 1) -> tuple[Rect, Rect]:
    """Split a rectangle into top and bottom panes, clamped to its height."""
    gap = min(max(0, gap), max(0, rect.height))
    usable = max(0, rect.height - gap)
    ratio = min(1.0, max(0.0, ratio))
    top_height = int(round(usable * ratio))
    bottom_height = usable - top_height
    return (Rect(rect.x, rect.y, rect.width, top_height),
            Rect(rect.x, rect.y + top_height + gap, rect.width, bottom_height))


def clip(value: object, width: int, ellipsis: str = "…") -> str:
    """Clip a string to a cell width without allowing a terminal wrap."""
    text = str(value)
    width = max(0, width)
    if len(text) <= width:
        return text
    if width == 0:
        return ""
    marker = ellipsis if len(ellipsis) <= width else ellipsis[:width]
    return text[:max(0, width - len(marker))] + marker


def wrap_text(value: object, width: int) -> list[str]:
    """Wrap prose into lines no wider than ``width`` cells."""
    width = max(1, width)
    lines: list[str] = []
    for paragraph in str(value).splitlines() or [""]:
        if not paragraph:
            lines.append("")
        else:
            lines.extend(textwrap.wrap(paragraph, width=width,
                                       break_long_words=True,
                                       break_on_hyphens=False) or [""])
    return lines


def _safe_addnstr(win, y: int, x: int, text: str, width: int, attr: int) -> None:
    if width <= 0:
        return
    try:
        win.addnstr(y, x, text, width, attr)
    except curses.error:
        # Curses reports an error when a write reaches the lower-right cell,
        # even when the visible write itself succeeded.
        pass


def draw_text(win, x: int, y: int, value: object, width: int,
              attr: int = 0, align: str = "left") -> None:
    """Draw one clipped line. ``align`` may be left, center, or right."""
    try:
        rows, cols = win.getmaxyx()
    except (AttributeError, curses.error):
        return
    if y < 0 or y >= rows or x < 0 or x >= cols:
        return
    width = min(max(0, width), cols - x)
    text = clip(value, width)
    if align == "right":
        text = text.rjust(width)
    elif align == "center":
        text = text.center(width)
    elif align != "left":
        raise ValueError("align must be 'left', 'center', or 'right'")
    else:
        text = text.ljust(width)
    _safe_addnstr(win, y, x, text, width, attr)


def draw_rule(win, x: int, y: int, width: int,
              glyph: str = "─", attr: int = 0) -> None:
    """Draw a horizontal separator clipped to the window."""
    try:
        rows, cols = win.getmaxyx()
    except (AttributeError, curses.error):
        return
    if y < 0 or y >= rows or x < 0 or x >= cols:
        return
    width = max(0, min(width, cols - x))
    if width:
        _safe_addnstr(win, y, x, glyph[:1] * width, width, attr)


def draw_panel(win, rect: Rect, title: str = "", attr: int = 0,
               title_attr: int | None = None) -> None:
    """Draw a simple bordered panel and an optional title in its top rule."""
    if rect.width < 2 or rect.height < 2:
        return
    draw_text(win, rect.x, rect.y, "┌" + "─" * (rect.width - 2) + "┐",
              rect.width, attr)
    for y in range(rect.y + 1, rect.bottom - 1):
        draw_text(win, rect.x, y, "│", 1, attr)
        draw_text(win, rect.right - 1, y, "│", 1, attr)
    draw_text(win, rect.x, rect.bottom - 1,
              "└" + "─" * (rect.width - 2) + "┘", rect.width, attr)
    if title and rect.width > 4:
        draw_text(win, rect.x + 2, rect.y, f" {title} ", rect.width - 4,
                  attr if title_attr is None else title_attr)


def key_action(key: int) -> str | None:
    """Map common curses keys and vi keys to neutral navigation actions."""
    actions = {
        curses.KEY_UP: "up", ord("k"): "up",
        curses.KEY_DOWN: "down", ord("j"): "down",
        curses.KEY_LEFT: "left", ord("h"): "left",
        curses.KEY_RIGHT: "right", ord("l"): "right",
        curses.KEY_PPAGE: "page_up", curses.KEY_NPAGE: "page_down",
        curses.KEY_HOME: "home", ord("g"): "home",
        curses.KEY_END: "end", ord("G"): "end",
        curses.KEY_ENTER: "select", 10: "select", 13: "select",
        27: "back", ord("q"): "back",
    }
    return actions.get(key)


@dataclass
class Viewport:
    """Selection and vertical scrolling state shared by lists and tables."""

    selected: int = 0
    offset: int = 0

    def sync(self, count: int, height: int) -> None:
        count, height = max(0, count), max(0, height)
        if count == 0 or height == 0:
            self.selected = self.offset = 0
            return
        self.selected = min(max(0, self.selected), count - 1)
        if self.selected < self.offset:
            self.offset = self.selected
        elif self.selected >= self.offset + height:
            self.offset = self.selected - height + 1
        self.offset = min(max(0, self.offset), max(0, count - height))

    def move(self, action: str, count: int, height: int) -> bool:
        """Apply a navigation action; return whether it was recognized."""
        count, height = max(0, count), max(0, height)
        if action in ("up", "down", "page_up", "page_down", "home", "end"):
            if count:
                if action == "up":
                    self.selected -= 1
                elif action == "down":
                    self.selected += 1
                elif action == "page_up":
                    self.selected -= max(1, height)
                elif action == "page_down":
                    self.selected += max(1, height)
                elif action == "home":
                    self.selected = 0
                else:
                    self.selected = count - 1
            self.sync(count, height)
            return True
        return False


class ListView:
    """A scrollable, selectable list. Enter returns its index; Esc/q returns -1."""

    def __init__(self, items: Sequence[object] = (), selected: int = 0) -> None:
        self.items = list(items)
        self.viewport = Viewport(selected=selected)

    @property
    def selected(self) -> int:
        return self.viewport.selected

    @property
    def current(self) -> object | None:
        if not self.items:
            return None
        return self.items[min(self.selected, len(self.items) - 1)]

    def set_items(self, items: Sequence[object]) -> None:
        self.items = list(items)
        self.viewport.sync(len(self.items), max(1, len(self.items)))

    def handle(self, key: int, height: int) -> int | None:
        self.viewport.sync(len(self.items), height)
        action = key_action(key)
        if action == "select":
            return self.selected if self.items else None
        if action == "back":
            return -1
        self.viewport.move(action or "", len(self.items), height)
        return None

    def draw(self, win, rect: Rect, selected_attr: int = curses.A_REVERSE,
             normal_attr: int = 0, marker: str = "›",
             empty: str = "(empty)") -> None:
        self.viewport.sync(len(self.items), rect.height)
        if not self.items:
            if rect.height:
                draw_text(win, rect.x, rect.y, empty, rect.width, normal_attr)
            return
        first, last = self.viewport.offset, min(len(self.items),
                                                self.viewport.offset + rect.height)
        for row, index in enumerate(range(first, last)):
            prefix = f"{marker} " if index == self.selected else "  "
            attr = selected_attr if index == self.selected else normal_attr
            draw_text(win, rect.x, rect.y + row,
                      prefix + str(self.items[index]), rect.width, attr)


class TableView:
    """A row-selectable table with clipped, automatically fitted columns."""

    def __init__(self, headers: Sequence[object],
                 rows: Sequence[Sequence[object]], selected: int = 0,
                 widths: Sequence[int] | None = None) -> None:
        self.headers = [str(value) for value in headers]
        self.rows = [list(row) for row in rows]
        self.preferred_widths = list(widths) if widths is not None else None
        self.viewport = Viewport(selected=selected)

    @property
    def selected(self) -> int:
        return self.viewport.selected

    def handle(self, key: int, height: int) -> int | None:
        self.viewport.sync(len(self.rows), max(0, height - 1))
        action = key_action(key)
        if action == "select":
            return self.selected if self.rows else None
        if action == "back":
            return -1
        self.viewport.move(action or "", len(self.rows), max(0, height - 1))
        return None

    def _widths(self, available: int) -> list[int]:
        count = len(self.headers)
        if count == 0 or available <= 0:
            return [0] * count
        natural = []
        for col, header in enumerate(self.headers):
            values = [len(header)]
            values.extend(len(str(row[col])) for row in self.rows
                          if col < len(row))
            preferred = (self.preferred_widths[col]
                         if self.preferred_widths and col < len(self.preferred_widths)
                         else max(values))
            natural.append(max(1, min(max(values), max(1, int(preferred)))))
        widths = [0] * count
        remaining = available
        active = list(range(count))
        while active and remaining > 0:
            share = max(1, remaining // len(active))
            next_active = []
            for col in active:
                give = min(natural[col], share, remaining)
                widths[col] += give
                remaining -= give
                if widths[col] < natural[col]:
                    next_active.append(col)
            if len(next_active) == len(active) and remaining == 0:
                break
            active = next_active
        return widths

    def draw(self, win, rect: Rect, selected_attr: int = curses.A_REVERSE,
             header_attr: int = curses.A_BOLD, normal_attr: int = 0,
             gap: int = 1) -> None:
        if not self.headers or rect.width <= 0 or rect.height <= 0:
            return
        gap = max(0, gap)
        available = max(0, rect.width - gap * (len(self.headers) - 1))
        widths = self._widths(available)
        x_positions = []
        x = rect.x
        for width in widths:
            x_positions.append(x)
            x += width + gap
        for col, header in enumerate(self.headers):
            draw_text(win, x_positions[col], rect.y, header, widths[col], header_attr)
        body_height = max(0, rect.height - 1)
        self.viewport.sync(len(self.rows), body_height)
        first = self.viewport.offset
        last = min(len(self.rows), first + body_height)
        for screen_row, index in enumerate(range(first, last), start=1):
            row = self.rows[index]
            attr = selected_attr if index == self.selected else normal_attr
            for col, width in enumerate(widths):
                value = str(row[col]) if col < len(row) else ""
                draw_text(win, x_positions[col], rect.y + screen_row,
                          value, width, attr)


class Tabs:
    """A compact horizontal tab bar with arrow, vi, Home/End, and number keys."""

    def __init__(self, labels: Sequence[object], selected: int = 0) -> None:
        self.labels = [str(label) for label in labels]
        self.selected = min(max(0, selected), max(0, len(self.labels) - 1))

    @property
    def current(self) -> str | None:
        return self.labels[self.selected] if self.labels else None

    def handle(self, key: int) -> bool:
        action = key_action(key)
        if action in ("left", "right", "home", "end") and self.labels:
            if action == "left":
                self.selected = max(0, self.selected - 1)
            elif action == "right":
                self.selected = min(len(self.labels) - 1, self.selected + 1)
            elif action == "home":
                self.selected = 0
            else:
                self.selected = len(self.labels) - 1
            return True
        if ord("1") <= key <= ord("9") and key - ord("1") < len(self.labels):
            self.selected = key - ord("1")
            return True
        return False

    def draw(self, win, x: int, y: int, width: int,
             selected_attr: int = curses.A_REVERSE,
             normal_attr: int = 0) -> None:
        width = max(0, width)
        if width == 0 or not self.labels:
            return

        selected_text = f"[{self.labels[self.selected]}]"
        if len(selected_text) > width:
            draw_text(win, x, y, selected_text, width, selected_attr)
            return

        # Keep the active tab visible even when the whole bar cannot fit.
        # Fill spare room with nearby tabs, preferring those before it.
        start = end = self.selected
        used = len(selected_text)
        while start > 0:
            token_width = len(f" {self.labels[start - 1]} ") + 1
            if used + token_width > width:
                break
            start -= 1
            used += token_width
        while end + 1 < len(self.labels):
            token_width = len(f" {self.labels[end + 1]} ") + 1
            if used + token_width > width:
                break
            end += 1
            used += token_width

        parts = []
        for i in range(start, end + 1):
            parts.append(f"[{self.labels[i]}]" if i == self.selected
                         else f" {self.labels[i]} ")
        draw_text(win, x, y, " ".join(parts), width, normal_attr)
        selected_offset = sum(len(part) + 1 for part in parts[:self.selected - start])
        selected_width = len(selected_text)
        draw_text(win, x + selected_offset, y, selected_text,
                  selected_width, selected_attr)
