"""VPK0 decoder (and a small test-only encoder) in pure Python.

The decoder is a line-for-line port of torch/lib/libvpk0/vpk0.c (itself a port of
the game's syDmaDecodeVpk0). The encoder exists only so the tests can build a
synthetic ROM without the real one; the game never sees its output.

Format (from the C source):
  "vpk0" magic, u32 BE decompressed size, u8 sample method,
  Huffman tree for offsets, Huffman tree for lengths (prefix notation:
  bit 0 = leaf + 8-bit value, bit 1 = combine the top two, bit 1 with fewer
  than two items on the stack = end of tree), then the stream:
  bit 0 = literal byte (8 bits), bit 1 = back-reference.
  Method 0: offset = tree(offsets) bits; copy from out - offset.
  Method != 0: v = tree bits; if v <= 2: sub = v + 1 and v = a second
  tree-coded value; copy from out - v * 4 - sub + 8.
  Length = tree(lengths) bits.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple, Union

MAGIC = b"vpk0"

Tree = Union[int, Tuple["Tree", "Tree"]]


class VPK0Error(ValueError):
    pass


class _BitReader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos
        self.acc = 0
        self.avail = 0

    def read(self, n: int) -> int:
        if n == 0:
            return 0
        while self.avail < n:
            if self.pos >= len(self.data):
                raise VPK0Error("vpk0 stream truncated")
            self.acc = (self.acc << 8) | self.data[self.pos]
            self.pos += 1
            self.avail += 8
        self.avail -= n
        value = (self.acc >> self.avail) & ((1 << n) - 1)
        self.acc &= (1 << self.avail) - 1
        return value


def _read_tree(bits: _BitReader) -> Tree:
    stack: List[Tree] = []
    nodes = 0
    while True:
        bit = bits.read(1)
        if bit and len(stack) < 2:
            break
        nodes += 1
        if nodes > 64:  # MAX_HUFF_NODES in the C decoder
            raise VPK0Error("vpk0 Huffman tree exceeds 64 nodes")
        if bit:
            right = stack.pop()
            left = stack.pop()
            stack.append((left, right))
        else:
            stack.append(bits.read(8))
    if not stack:
        raise VPK0Error("vpk0 empty Huffman tree")
    return stack[0]


def _tree_value(bits: _BitReader, tree: Tree) -> int:
    node = tree
    while isinstance(node, tuple):
        node = node[1] if bits.read(1) else node[0]
    return node


def decoded_size(src: bytes) -> int:
    if len(src) < 8 or src[:4] != MAGIC:
        raise VPK0Error("not a vpk0 stream (bad magic)")
    return int.from_bytes(src[4:8], "big")


def decode(src: bytes) -> bytes:
    size = decoded_size(src)
    if size == 0:
        raise VPK0Error("vpk0 decompressed size is 0")
    bits = _BitReader(src, 4)
    bits.read(16)
    bits.read(16)
    method = bits.read(8)
    offsets = _read_tree(bits)
    lengths = _read_tree(bits)
    out = bytearray()
    while len(out) < size:
        if bits.read(1) == 0:
            out.append(bits.read(8))
            continue
        if method != 0:
            sub = 0
            value = bits.read(_tree_value(bits, offsets))
            if value <= 2:
                sub = value + 1
                value = bits.read(_tree_value(bits, offsets))
            src_pos = len(out) - value * 4 - sub + 8
        else:
            src_pos = len(out) - bits.read(_tree_value(bits, offsets))
        length = bits.read(_tree_value(bits, lengths))
        if src_pos < 0 or src_pos >= len(out) and length > 0:
            raise VPK0Error(f"vpk0 back-reference before start of output (src {src_pos}, out {len(out)})")
        for _ in range(length):
            out.append(out[src_pos])
            src_pos += 1
    return bytes(out[:size])


# -- test-only encoder ---------------------------------------------------------------------------------


class _BitWriter:
    def __init__(self) -> None:
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def write(self, value: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> i) & 1)
            self.n += 1
            if self.n == 8:
                self.out.append(self.acc)
                self.acc = 0
                self.n = 0

    def flush(self) -> bytes:
        if self.n:
            self.out.append(self.acc << (8 - self.n))
            self.acc = 0
            self.n = 0
        return bytes(self.out)


def _write_balanced_tree(w: _BitWriter, leaves: Sequence[int]) -> Dict[int, Tuple[int, int]]:
    """Serialise a balanced tree over `leaves` (power-of-two count) and return leaf -> (code, code_len)."""
    if len(leaves) & (len(leaves) - 1):
        raise ValueError("leaf count must be a power of two")
    depth = len(leaves).bit_length() - 1

    def emit(lo: int, hi: int) -> None:
        if hi - lo == 1:
            w.write(0, 1)
            w.write(leaves[lo], 8)
            return
        mid = (lo + hi) // 2
        emit(lo, mid)
        emit(mid, hi)
        w.write(1, 1)

    emit(0, len(leaves))
    w.write(1, 1)  # end of tree (one item left on the stack)
    return {leaf: (i, depth) for i, leaf in enumerate(leaves)}


def encode(data: bytes, method: int = 0, offset_bits: Sequence[int] = (4, 8, 12, 16),
           length_bits: Sequence[int] = (2, 4, 6, 8)) -> bytes:
    """Greedy LZ encoder producing a stream `decode` (and the C reference decoder) accept. Test use only."""
    w = _BitWriter()
    for b in MAGIC:
        w.write(b, 8)
    w.write(len(data), 32)
    w.write(method, 8)
    off_codes = _write_balanced_tree(w, sorted(offset_bits))
    len_codes = _write_balanced_tree(w, sorted(length_bits))
    max_len = (1 << max(length_bits)) - 1
    max_val = (1 << max(offset_bits)) - 1
    min_len = 3

    def put_tree_value(codes: Dict[int, Tuple[int, int]], value: int) -> None:
        for nbits in sorted(codes):
            if value < (1 << nbits):
                code, code_len = codes[nbits]
                w.write(code, code_len)
                w.write(value, nbits)
                return
        raise ValueError("value does not fit the tree")

    def distance_ok(d: int) -> bool:
        if method == 0:
            return 1 <= d <= max_val
        r = (d + 8) % 4
        return d >= 1 and (d + 8 - r) // 4 <= max_val

    index: Dict[bytes, List[int]] = {}
    i = 0
    n = len(data)
    while i < n:
        best_len = 0
        best_d = 0
        key = data[i:i + min_len]
        if len(key) == min_len:
            for j in reversed(index.get(key, [])[-64:]):
                d = i - j
                if not distance_ok(d):
                    continue
                k = 0
                while i + k < n and k < max_len and data[j + k] == data[i + k]:
                    k += 1
                if k > best_len:
                    best_len, best_d = k, d
        if best_len >= min_len:
            w.write(1, 1)
            if method == 0:
                put_tree_value(off_codes, best_d)
            else:
                r = (best_d + 8) % 4
                if r == 0:
                    put_tree_value(off_codes, (best_d + 8) // 4)  # always > 2 for d >= 4
                else:
                    put_tree_value(off_codes, r - 1)
                    put_tree_value(off_codes, (best_d + 8 - r) // 4)
            put_tree_value(len_codes, best_len)
            step = best_len
        else:
            w.write(0, 1)
            w.write(data[i], 8)
            step = 1
        for p in range(i, min(i + step, n - min_len + 1)):
            index.setdefault(data[p:p + min_len], []).append(p)
        i += step
    return w.flush()


def decode_if_vpk0(blob: bytes) -> Tuple[bytes, Optional[int]]:
    """(decoded bytes, method) for a vpk0 blob, or (blob, None) when it is stored uncompressed."""
    if blob[:4] == MAGIC:
        return decode(blob), blob[8]
    return blob, None
