#!/usr/bin/env python3
"""Blackjack -- six decks, dealer stands on soft 17.

A line-based game: plain input() and ts.tv_print(), no curses. This is the simplest
shape a TermStation game can take.
"""
from __future__ import annotations

import random
import sys

import termstation_sdk as ts

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
DECKS = 6
STARTING_CHIPS = 500
BLACKJACK_PAYOUT = 1.5


class Card:
    __slots__ = ("rank", "suit")

    def __init__(self, rank: str, suit: str) -> None:
        self.rank, self.suit = rank, suit

    @property
    def value(self) -> int:
        if self.rank in ("J", "Q", "K"):
            return 10
        if self.rank == "A":
            return 11
        return int(self.rank)

    @property
    def red(self) -> bool:
        return self.suit in ("♥", "♦")

    def __str__(self) -> str:
        face = f"{self.rank}{self.suit}"
        return ts.color(face, "bright_red" if self.red else "white")


class Shoe:
    """Six decks, reshuffled when a quarter remains -- as in a real pit."""

    def __init__(self, decks: int = DECKS) -> None:
        self.decks = decks
        self.cards: list[Card] = []
        self.shuffle()

    def shuffle(self) -> None:
        self.cards = [Card(r, s) for _ in range(self.decks) for s in SUITS for r in RANKS]
        random.shuffle(self.cards)
        self.reshuffle_at = len(self.cards) // 4

    def draw(self) -> Card:
        if len(self.cards) <= self.reshuffle_at:
            self.shuffle()
            ts.tv_print(ts.color("  ── shoe reshuffled ──", "grey"))
        return self.cards.pop()


def hand_value(cards: list[Card]) -> int:
    """Best total <= 21, demoting aces from 11 to 1 as needed."""
    total = sum(c.value for c in cards)
    aces = sum(1 for c in cards if c.rank == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[Card]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def show(cards: list[Card], hidden: bool = False) -> str:
    if hidden:
        return f"{cards[0]} {ts.color('[??]', 'grey')}"
    return " ".join(str(c) for c in cards)


PAGE = 17  # rows a hand screen uses, so the page sits centred in the picture

MOVES = {
    "hit": "take another card",
    "stand": "keep what you have",
    "double": "double your bet, take exactly one more card",
    "split": "split the pair into two hands",
}


def header(chips: int, bet: int | None = None) -> None:
    ts.tv_clear(page=PAGE)
    ts.tv_print(ts.title("B L A C K J A C K"))
    line = f"  chips: {ts.color(str(chips), 'bright_yellow', bold=True)}"
    if bet:
        line += f"    bet: {ts.color(str(bet), 'bright_cyan')}"
    line += f"    {ts.color(ts.profile(), 'grey')}"
    ts.tv_print(line)
    ts.tv_print()


# ---------------------------------------------------------------- wallet

def load_chips() -> int:
    """Chips live in the shared profile wallet, so every casino game agrees."""
    wallet = _wallet()
    return int(wallet.get("chips", STARTING_CHIPS))


def _wallet() -> dict:
    path = ts.shared_dir() / "wallet.json"
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def store_chips(chips: int) -> None:
    import json
    path = ts.shared_dir() / "wallet.json"
    data = _wallet()
    data["chips"] = chips
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- play

def play_hand(shoe: Shoe, cards: list[Card], bet: int, chips: int,
              dealer: list[Card], can_split: bool = True) -> list[tuple[list[Card], int]]:
    """Play one hand to completion. Returns [(cards, bet)] -- more than one if split."""
    while True:
        header(chips, bet)
        ts.tv_print(f"  dealer  {show(dealer, hidden=True)}")
        ts.tv_print(f"  you     {show(cards)}   {ts.color(str(hand_value(cards)), 'bright_green', bold=True)}")
        ts.tv_print()

        if hand_value(cards) >= 21:
            return [(cards, bet)]

        options = ["hit", "stand"]
        if len(cards) == 2 and chips >= bet:
            options.append("double")
        if (can_split and len(cards) == 2 and chips >= bet
                and cards[0].value == cards[1].value):
            options.append("split")

        ts.tv_print(ts.color("  your options", "bright_yellow", bold=True))
        for i, opt in enumerate(options, 1):
            ts.tv_print(f"   {ts.color(str(i), 'bright_cyan')}  "
                        f"{ts.color(opt.ljust(7), 'white', bold=True)} {MOVES[opt]}")
        ts.tv_print(ts.color("   type the word or its number, then enter", "grey"))
        ts.tv_print()
        move = ts.ask_choice("your move", options)

        if move == "hit":
            cards.append(shoe.draw())
            if hand_value(cards) > 21:
                header(chips, bet)
                ts.tv_print(f"  you     {show(cards)}   {ts.color('BUST', 'bright_red', bold=True)}")
                return [(cards, bet)]
        elif move == "stand":
            return [(cards, bet)]
        elif move == "double":
            cards.append(shoe.draw())
            return [(cards, bet * 2)]
        elif move == "split":
            left = [cards[0], shoe.draw()]
            right = [cards[1], shoe.draw()]
            ts.tv_print(ts.color("  splitting...", "bright_cyan"))
            ts.tv_pause()
            out = play_hand(shoe, left, bet, chips - bet, dealer, can_split=False)
            out += play_hand(shoe, right, bet, chips - bet, dealer, can_split=False)
            return out


def dealer_turn(shoe: Shoe, dealer: list[Card]) -> None:
    while hand_value(dealer) < 17:
        dealer.append(shoe.draw())


def settle(player: list[Card], bet: int, dealer: list[Card]) -> tuple[int, str]:
    """Returns (chip delta, verdict)."""
    p, d = hand_value(player), hand_value(dealer)
    if p > 21:
        return -bet, ts.color("bust — you lose", "bright_red")
    if is_blackjack(player) and not is_blackjack(dealer):
        return int(bet * BLACKJACK_PAYOUT), ts.color("BLACKJACK!", "bright_yellow", bold=True)
    if d > 21:
        return bet, ts.color("dealer busts — you win", "bright_green")
    if p > d:
        return bet, ts.color("you win", "bright_green")
    if p < d:
        return -bet, ts.color("dealer wins", "bright_red")
    return 0, ts.color("push", "grey")


def main() -> int:
    ts.tv("Blackjack")
    save = ts.load({"hands": 0, "wins": 0, "biggest_win": 0})
    chips = load_chips()
    shoe = Shoe()

    ts.tv_clear(page=17)
    ts.tv_print(ts.title("B L A C K J A C K"))
    ts.tv_print()
    ts.tv_print(ts.box([
        "  HOW TO PLAY",
        "",
        "  Beat the dealer by getting closer to 21 without going over.",
        "  Cards are face value, pictures are 10, an ace is 11 or 1.",
        "",
        "  Bet, then choose: hit, stand, double or split.",
        "  Type the word or the number beside it, then press enter.",
        "",
        "  Six decks. Dealer stands on soft 17. Blackjack pays 3:2.",
        f"  You sit down with {chips} chips.",
    ]))
    ts.tv_pause("press enter to play")

    while True:
        if chips <= 0:
            header(chips)
            ts.tv_print(ts.color("\n  You're out of chips.\n", "bright_red"))
            if ts.confirm("  Take a 100 chip marker from the house?"):
                chips = 100
            else:
                break

        header(chips)
        ts.tv_print(f"  hands played {save['hands']}   won {save['wins']}")
        ts.tv_print()
        ts.tv_print(ts.color("  place your bet for the next hand", "bright_yellow",
                             bold=True))
        ts.tv_print(ts.color("  type a number and press enter, or 0 to cash out",
                             "grey"))
        ts.tv_print(ts.color("  (just press enter to bet the amount in brackets)",
                             "grey"))
        ts.tv_print()
        bet = ts.ask_int(f"bet (1-{chips}, 0 to leave)", 0, chips, min(25, chips))
        if bet == 0:
            break

        player = [shoe.draw(), shoe.draw()]
        dealer = [shoe.draw(), shoe.draw()]

        # insurance
        if dealer[0].rank == "A" and chips >= bet + bet // 2:
            header(chips, bet)
            ts.tv_print(f"  dealer  {show(dealer, hidden=True)}")
            ts.tv_print(f"  you     {show(player)}")
            ts.tv_print()
            if ts.confirm(f"  insurance for {bet // 2}?", default=False):
                if is_blackjack(dealer):
                    chips += bet // 2
                    ts.tv_print(ts.color("  insurance pays 2:1", "bright_green"))
                else:
                    chips -= bet // 2
                    ts.tv_print(ts.color("  insurance lost", "bright_red"))
                ts.tv_pause()

        if is_blackjack(player) or is_blackjack(dealer):
            results = [(player, bet)]
        else:
            results = play_hand(shoe, player, bet, chips, dealer)

        if any(hand_value(c) <= 21 for c, _ in results):
            dealer_turn(shoe, dealer)

        header(chips, bet)
        ts.tv_print(f"  dealer  {show(dealer)}   {ts.color(str(hand_value(dealer)), 'bright_yellow')}")
        ts.tv_print()
        total_delta = 0
        for cards, wager in results:
            delta, verdict = settle(cards, wager, dealer)
            total_delta += delta
            ts.tv_print(f"  you     {show(cards)}   {hand_value(cards):>3}   {verdict}")

        chips += total_delta
        save["hands"] += 1
        if total_delta > 0:
            save["wins"] += 1
            save["biggest_win"] = max(save["biggest_win"], total_delta)
            ts.unlock("first-win", "House Money", "Won a hand")
            if any(is_blackjack(c) for c, _ in results):
                ts.unlock("natural", "Natural", "Was dealt twenty-one")
        if chips >= 1000:
            ts.unlock("high-roller", "High Roller", "Sat on a thousand chips")

        ts.tv_print()
        sign = "+" if total_delta > 0 else ""
        tone = "bright_green" if total_delta > 0 else "bright_red" if total_delta < 0 else "grey"
        ts.tv_print(f"  {ts.color(sign + str(total_delta), tone, bold=True)} chips   "
              f"total {ts.color(str(chips), 'bright_yellow', bold=True)}")
        ts.tv_print()
        ts.tv_pause()

        store_chips(chips)
        ts.save(save)

    store_chips(chips)
    ts.save(save)
    header(chips)
    ts.tv_print(ts.box([
        f"  hands played   {save['hands']}",
        f"  hands won      {save['wins']}",
        f"  biggest win    {save['biggest_win']}",
        f"  chips banked   {chips}",
    ], fg="yellow"))
    ts.tv_print(ts.color("\n  the house thanks you.\n", "cyan"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
