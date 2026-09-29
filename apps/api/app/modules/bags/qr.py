"""Minimal, dependency-free QR Code encoder (ISO/IEC 18004) for bag labels.

Byte mode, error-correction level M, versions 1-4 (up to 62 bytes: a bag payload like
``veyra:bag:VYR-7F3K-2QXM`` is 23 bytes → version 2, 25x25 modules). Deterministic: the same
payload always yields the same matrix. The QR only carries the public bag identifier; it is a
traceability label, never an authentication credential or medical authorization.
"""

from __future__ import annotations

from typing import Final

# (total codewords, EC codewords per block, blocks) for level M, versions 1..4
_SPECS: Final[dict[int, tuple[int, int, int]]] = {
    1: (26, 10, 1),
    2: (44, 16, 1),
    3: (70, 26, 1),
    4: (100, 18, 2),
}
MAX_BYTES: Final = 62


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _codewords(payload: bytes, version: int) -> list[int]:
    total, ecc, blocks = _SPECS[version]
    data_len = total - ecc * blocks
    bits: list[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> i) & 1 for i in range(length - 1, -1, -1))

    put(0b0100, 4)  # byte mode
    put(len(payload), 8)
    for b in payload:
        put(b, 8)
    capacity = data_len * 8
    put(0, min(4, capacity - len(bits)))  # terminator
    put(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    data = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, capacity, 8)]
    per_block = data_len // blocks
    divisor = _rs_divisor(ecc)
    data_blocks = [data[i * per_block : (i + 1) * per_block] for i in range(blocks)]
    ecc_blocks = [_rs_remainder(b, divisor) for b in data_blocks]
    out = [blk[i] for i in range(per_block) for blk in data_blocks]
    out += [blk[i] for i in range(ecc) for blk in ecc_blocks]
    return out


class _Matrix:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = version * 4 + 17
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x: int, y: int, dark: bool) -> None:
        self.mod[y][x] = dark
        self.fn[y][x] = True

    def draw_function_patterns(self) -> None:
        n = self.size
        for i in range(n):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        dist = max(abs(dx), abs(dy))
                        self.set_fn(x, y, dist not in (2, 4))
        if self.version >= 2:
            c = n - 7
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    self.set_fn(c + dx, c + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)

    def draw_format(self, mask: int) -> None:
        data = (0 << 3) | mask  # level M = 0b00
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412
        n = self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, bit(i))
        self.set_fn(8, n - 8, True)  # the always-dark module

    def draw_codewords(self, data: list[int]) -> None:
        n = self.size
        total_bits = len(data) * 8
        i = 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < total_bits:
                        self.mod[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.fn[y][x]:
                    continue
                flip = (
                    (x + y) % 2 == 0,
                    y % 2 == 0,
                    x % 3 == 0,
                    (x + y) % 3 == 0,
                    (x // 3 + y // 2) % 2 == 0,
                    x * y % 2 + x * y % 3 == 0,
                    (x * y % 2 + x * y % 3) % 2 == 0,
                    ((x + y) % 2 + x * y % 3) % 2 == 0,
                )[mask]
                if flip:
                    self.mod[y][x] = not self.mod[y][x]

    def penalty(self) -> int:
        n, m = self.size, self.mod
        score = 0
        lines = [m[y] for y in range(n)] + [[m[y][x] for y in range(n)] for x in range(n)]
        finder = [True, False, True, True, True, False, True]
        for line in lines:
            run, prev = 0, None
            for v in line:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run, prev = 1, v
            if run >= 5:
                score += 3 + run - 5
            padded = [False] * 4 + list(line) + [False] * 4
            for k in range(len(padded) - 10):
                window = padded[k : k + 11]
                if (window[:7] == finder and not any(window[7:])) or (
                    window[4:] == finder and not any(window[:4])
                ):
                    score += 40
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(v for row in m for v in row)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        return score + max(k, 0) * 10


def encode(payload: str) -> list[str]:
    """QR matrix rows as '1' (dark) / '0' (light) strings, without the quiet zone."""
    raw = payload.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("payload too long for a bag label QR")
    version = next(
        v for v, (total, ecc, blocks) in _SPECS.items() if len(raw) <= total - ecc * blocks - 2
    )
    data = _codewords(raw, version)
    best: _Matrix | None = None
    best_score = 0
    for mask in range(8):
        mx = _Matrix(version)
        mx.draw_function_patterns()
        mx.draw_codewords(data)
        mx.apply_mask(mask)
        mx.draw_format(mask)
        score = mx.penalty()
        if best is None or score < best_score:
            best, best_score = mx, score
    assert best is not None  # noqa: S101 - eight candidates always exist
    return ["".join("1" if v else "0" for v in row) for row in best.mod]
