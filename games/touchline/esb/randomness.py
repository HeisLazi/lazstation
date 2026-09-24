"""Named, serializable deterministic streams independent of Python hash/RNG state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_MASK64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_DEFAULT_STREAMS = ("football", "world", "reporting")


def _stream_seed(root_seed: int, name: str) -> int:
    raw = f"esb-stream-v1\0{root_seed}\0{name}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")


@dataclass
class RandomStream:
    name: str
    state: int
    draws: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("random stream name must be non-empty")
        if type(self.state) is not int or not 0 <= self.state <= _MASK64:
            raise ValueError("random stream state must be an unsigned 64-bit integer")
        if type(self.draws) is not int or self.draws < 0:
            raise ValueError("random stream draw count must be non-negative")

    def next_u64(self) -> int:
        self.state = (self.state + _GAMMA) & _MASK64
        self.draws += 1
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
        return (value ^ (value >> 31)) & _MASK64

    def random(self) -> float:
        """Return a uniform 53-bit fraction in [0, 1)."""
        return (self.next_u64() >> 11) / (1 << 53)

    def randbelow(self, bound: int) -> int:
        if type(bound) is not int or bound <= 0:
            raise ValueError("random bound must be a positive integer")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound


@dataclass
class RandomStreams:
    root_seed: int
    streams: dict[str, RandomStream]
    algorithm: str = "splitmix64-v1"

    def __post_init__(self) -> None:
        if type(self.root_seed) is not int:
            raise TypeError("root seed must be an integer")
        if self.algorithm != "splitmix64-v1":
            raise ValueError("unsupported deterministic random algorithm")
        if not isinstance(self.streams, dict):
            raise TypeError("random streams must be stored by explicit name")
        missing = set(_DEFAULT_STREAMS) - set(self.streams)
        if missing:
            raise ValueError(f"random state is missing required streams: {', '.join(sorted(missing))}")
        for name, stream in self.streams.items():
            if not isinstance(name, str) or not isinstance(stream, RandomStream):
                raise TypeError("random stream map must contain named RandomStream records")
            if name != stream.name:
                raise ValueError("random stream map key must match its stream name")

    @classmethod
    def seeded(cls, seed: int) -> RandomStreams:
        return cls(
            root_seed=seed,
            streams={name: RandomStream(name, _stream_seed(seed, name)) for name in _DEFAULT_STREAMS},
        )

    def stream(self, name: str) -> RandomStream:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("random stream name must be non-empty")
        if name not in self.streams:
            self.streams[name] = RandomStream(name, _stream_seed(self.root_seed, name))
        return self.streams[name]
