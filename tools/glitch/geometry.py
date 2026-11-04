"""Stage collision geometry for Break the Targets: ROM extraction, decomp-source decode, trace decode,
and the game's derived line tables.

Sources of truth (decomp, read-only):
  - layouts: decomp/src/mp/mptypes.h (MPGeometryData, MPLineInfo, MPVertexData, MPVertexLinks,
    MPMapObjData) and MPGroundData (map header);
  - derived tables: func_ovl2_800FB04C (coll_pos_next / coll_pos_prev, yakumono id by running index),
    mpCollisionInitLineTypesAll (line type), func_ovl2_800FB31C (edge links) in decomp/src/mp/mpcollision.c;
  - relocation: lbRelocLoadAndRelocFile in decomp/src/lb/lbreloc.c (intern chain, extern chain with
    file ids after the compressed data);
  - ROM table: tools/generate_yamls.py (US table at 0x1AC870, 2132 files; JP at 0x1ACAF0, 2107 files).

Nothing here touches the game. The ROM is read only, locally; no ROM byte is written anywhere except the
geometry JSON the caller asks for.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import vpk0

SCHEMA = "btt_glitch_geometry_v1"

KIND_FLOOR, KIND_CEIL, KIND_RWALL, KIND_LWALL = 0, 1, 2, 3
KIND_NAMES = ("floor", "ceil", "rwall", "lwall")
VERTEX_COLL_PASS = 0x4000   # MAP_VERTEX_COLL_PASS: line can be passed through (drop-through, one-way)
VERTEX_COLL_CLIFF = 0x8000  # MAP_VERTEX_COLL_CLIFF: ledge can be grabbed
VERTEX_MAT_MASK = 0x00FF    # material in the low byte

RELOC_ENTRY = struct.Struct(">IHHHH")
VERSIONS: Dict[str, Dict[str, int]] = {
    # tools/generate_yamls.py VERSIONS
    "us": {"reloc_table": 0x001AC870, "file_count": 2132, "header_file": 271},
    "jp": {"reloc_table": 0x001ACAF0, "file_count": 2107, "header_file": -1},  # -1: look up GRBonus1MarioMap in yamls/jp
}
HEADER_SYMBOL = "GRBonus1MarioMap"
HEADER_MAP_GEOMETRY_SLOT = 0x40  # MPGroundData.map_geometry (after gr_desc[4], 4 x 16 bytes)

# MPGroundData offsets (N64 layout, big-endian; see mptypes.h). Only the bounds are read.
HEADER_FIELDS_S16 = {
    "camera_bound_top": 0x6C, "camera_bound_bottom": 0x6E, "camera_bound_right": 0x70, "camera_bound_left": 0x72,
    "map_bound_top": 0x74, "map_bound_bottom": 0x76, "map_bound_right": 0x78, "map_bound_left": 0x7A,
    "alt_warning": 0x88,
}


class GeometryError(ValueError):
    pass


# -- raw structures -------------------------------------------------------------------------------------


@dataclass
class Vertex:
    x: int
    y: int
    flags: int


@dataclass
class LineInfo:
    yakumono_id: int
    data: List[Tuple[int, int]]  # (group_id = first line id, line_count) per kind, in kind order


@dataclass
class RawGeometry:
    yakumono_count: int
    vertices: List[Vertex]
    vertex_ids: List[int]
    links: List[Tuple[int, int]]           # (first index into vertex_ids, vertex count)
    line_info: List[LineInfo]
    mapobjs: List[Tuple[int, int, int]]    # (kind, x, y)
    regions: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # name -> (file offset, bytes)
    source: Dict[str, Any] = field(default_factory=dict)
    header: Dict[str, int] = field(default_factory=dict)


# -- derived game tables ----------------------------------------------------------------------------------


@dataclass
class Line:
    id: int
    kind: int
    group: int                 # yakumono id of the MPLineInfo range that holds this id (what the sweep loops use)
    group_seq: int             # yakumono id the game stores in vertex_info[id] (running-index assignment)
    vertex_index: List[int]    # indices into the vertex table
    points: List[Tuple[float, float]]
    vflags: List[int]          # per-vertex flags; a segment uses the flags of its first vertex
    coll_near: int             # vertex_info.coll_pos_prev as the game computes it (running index)
    coll_far: int              # vertex_info.coll_pos_next
    edge_next: int = -1        # line at the +x end (floor/ceil) or +y end (walls); -1 = none
    edge_prev: int = -1

    @property
    def kind_name(self) -> str:
        return KIND_NAMES[self.kind]

    @property
    def flags_first(self) -> int:
        return self.vflags[0] if self.vflags else 0

    def segments(self) -> List[Tuple[Tuple[float, float], Tuple[float, float], int]]:
        return [(self.points[i], self.points[i + 1], self.vflags[i]) for i in range(len(self.points) - 1)]

    @property
    def is_pass(self) -> bool:
        return any(f & VERTEX_COLL_PASS for _, _, f in self.segments())

    @property
    def is_cliff(self) -> bool:
        return any(f & VERTEX_COLL_CLIFF for _, _, f in self.segments())


@dataclass
class Geometry:
    lines: List[Line]
    raw: Optional[RawGeometry] = None
    origin: str = "unknown"
    header: Dict[str, int] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def line(self, line_id: int) -> Line:
        return self.lines[line_id]

    def sha256(self) -> str:
        canon = [[l.id, l.kind, l.group, [list(p) for p in l.points], l.vflags] for l in self.lines]
        return hashlib.sha256(json.dumps(canon, separators=(",", ":")).encode()).hexdigest()

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema": SCHEMA,
            "origin": self.origin,
            "geometry_sha256": self.sha256(),
            "header": dict(self.header),
            "notes": list(self.notes),
            "lines": [{
                "id": l.id, "kind": l.kind_name, "type": l.kind, "group": l.group, "group_seq": l.group_seq,
                "points": [list(p) for p in l.points], "vertex_index": l.vertex_index, "vertex_flags": l.vflags,
                "flags_first": l.flags_first, "pass": l.is_pass, "cliff": l.is_cliff,
                "materials": sorted({f & VERTEX_MAT_MASK for f in l.vflags}),
                "coll_pos": [l.coll_near, l.coll_far], "edge_next": l.edge_next, "edge_prev": l.edge_prev,
            } for l in self.lines],
        }
        if self.raw is not None:
            r = self.raw
            out["raw"] = {
                "yakumono_count": r.yakumono_count,
                "vertices": [[v.x, v.y, v.flags] for v in r.vertices],
                "vertex_ids": list(r.vertex_ids),
                "links": [list(k) for k in r.links],
                "line_info": [[li.yakumono_id, [list(d) for d in li.data]] for li in r.line_info],
                "mapobjs": [list(m) for m in r.mapobjs],
                "regions": {k: list(v) for k, v in r.regions.items()},
                "source": r.source,
            }
        return out


def derive(raw: RawGeometry, origin: str) -> Geometry:
    """The game's derived tables, computed the way mpCollisionInitGroundData does (including its assumptions)."""
    notes: List[str] = []
    total = sum(c for li in raw.line_info for _, c in li.data)
    if total != len(raw.links):
        raise GeometryError(f"line_info counts {total} lines but there are {len(raw.links)} vertex links")
    kind_of = [-1] * total
    group_of = [-1] * total
    for li in raw.line_info:  # mpCollisionInitLineIDsAll + mpCollisionInitLineTypesAll
        for kind, (first, count) in enumerate(li.data):
            for lid in range(first, first + count):
                if not 0 <= lid < total:
                    raise GeometryError(f"line id {lid} out of range (total {total})")
                if kind_of[lid] != -1:
                    notes.append(f"line {lid} is listed twice in line_info (kinds {kind_of[lid]} and {kind})")
                kind_of[lid] = kind
                group_of[lid] = li.yakumono_id
    missing = [i for i, k in enumerate(kind_of) if k == -1]
    if missing:
        raise GeometryError(f"lines without a kind: {missing}")

    def vpos(k: int) -> Vertex:
        vid = raw.vertex_ids[k]
        if not 0 <= vid < len(raw.vertices):
            raise GeometryError(f"vertex id {vid} out of range")
        return raw.vertices[vid]

    # func_ovl2_800FB04C: coll_pos / yakumono id stored at a running index l, not at the line id.
    seq_group = [-1] * total
    seq_near = [0] * total
    seq_far = [0] * total
    l = 0
    for li in raw.line_info:
        for kind, (first, count) in enumerate(li.data):
            for k in range(count):
                v1, n = raw.links[first + k]
                use_y = kind < 2
                vals = [(vpos(v1 + j).y if use_y else vpos(v1 + j).x) for j in range(n)]
                seq_near[l], seq_far[l], seq_group[l] = min(vals), max(vals), li.yakumono_id
                l += 1
    lines: List[Line] = []
    for lid in range(total):
        v1, n = raw.links[lid]
        idx = [raw.vertex_ids[v1 + j] for j in range(n)]
        pts = [(float(raw.vertices[i].x), float(raw.vertices[i].y)) for i in idx]
        lines.append(Line(id=lid, kind=kind_of[lid], group=group_of[lid], group_seq=seq_group[lid], vertex_index=idx,
                          points=pts, vflags=[raw.vertices[i].flags for i in idx], coll_near=seq_near[lid],
                          coll_far=seq_far[lid]))
    # func_ovl2_800FB31C: endpoints matched by vertex index; the last match wins.
    for line in lines:
        a, b = line.vertex_index[0], line.vertex_index[-1]
        prev_id = next_id = -1
        for other in lines:
            if other.id == line.id:
                continue
            ends = (other.vertex_index[0], other.vertex_index[-1])
            if a in ends:
                prev_id = other.id
            if b in ends:
                next_id = other.id
        pa, pb = raw.vertices[a], raw.vertices[b]
        swap = (pb.x < pa.x) if line.kind in (KIND_FLOOR, KIND_CEIL) else (pb.y < pa.y)
        line.edge_next, line.edge_prev = (prev_id, next_id) if swap else (next_id, prev_id)
    g = Geometry(lines=lines, raw=raw, origin=origin, header=dict(raw.header), notes=notes)
    return g


# -- parsing a file image (N64 layout) ----------------------------------------------------------------------


def chain_map(image: bytes, start_word: int) -> Dict[int, int]:
    """Relocation chain (lbreloc.c): slot byte offset -> target byte offset, in chain order."""
    out: Dict[int, int] = {}
    cur = start_word
    for _ in range(len(image) // 4 + 1):
        if cur == 0xFFFF:
            return out
        slot = cur * 4
        if slot + 4 > len(image):
            raise GeometryError(f"relocation chain leaves the file (slot 0x{slot:X})")
        word = int.from_bytes(image[slot:slot + 4], "big")
        out[slot] = (word & 0xFFFF) * 4
        cur = word >> 16
    raise GeometryError("relocation chain does not terminate")


def parse_geometry_image(image: bytes, offset: int, intern: Optional[Mapping[int, int]] = None) -> RawGeometry:
    """Parse MPGeometryData at `offset` of a decompressed file image. Pointer slots are decoded through the
    intern chain when given (and must be on it), else from the low 16 bits (the chain's target word)."""
    def u16(o: int) -> int:
        return int.from_bytes(image[o:o + 2], "big")

    def s16(o: int) -> int:
        return int.from_bytes(image[o:o + 2], "big", signed=True)

    def ptr(slot: int) -> int:
        if intern is not None:
            if slot not in intern:
                raise GeometryError(f"pointer slot 0x{slot:X} is not on the intern relocation chain")
            return intern[slot]
        return (int.from_bytes(image[slot:slot + 4], "big") & 0xFFFF) * 4

    if offset + 28 > len(image):
        raise GeometryError("MPGeometryData beyond the end of the file")
    yakumono_count = u16(offset)
    p_vertex, p_ids, p_links, p_info = ptr(offset + 4), ptr(offset + 8), ptr(offset + 12), ptr(offset + 16)
    mapobj_count = u16(offset + 20)
    p_mapobjs = ptr(offset + 24) if mapobj_count else 0
    if not 0 < yakumono_count <= 32:
        raise GeometryError(f"implausible yakumono_count {yakumono_count}")
    info: List[LineInfo] = []
    for i in range(yakumono_count):
        o = p_info + 18 * i
        info.append(LineInfo(u16(o), [(u16(o + 2 + 4 * k), u16(o + 4 + 4 * k)) for k in range(4)]))
    total = sum(c for li in info for _, c in li.data)
    if not 0 < total <= 4096:
        raise GeometryError(f"implausible line total {total}")
    links = [(u16(p_links + 4 * i), u16(p_links + 4 * i + 2)) for i in range(total)]
    n_ids = max(a + b for a, b in links)
    ids = [u16(p_ids + 2 * i) for i in range(n_ids)]
    n_vertices = max(ids) + 1
    vertices = [Vertex(s16(p_vertex + 6 * i), s16(p_vertex + 6 * i + 2), u16(p_vertex + 6 * i + 4))
                for i in range(n_vertices)]
    mapobjs = [(u16(p_mapobjs + 6 * i), s16(p_mapobjs + 6 * i + 2), s16(p_mapobjs + 6 * i + 4))
               for i in range(mapobj_count)]
    regions = {"vertex_data": (p_vertex, 6 * n_vertices), "vertex_id": (p_ids, 2 * n_ids),
               "vertex_links": (p_links, 4 * total), "line_info": (p_info, 18 * yakumono_count),
               "mapobjs": (p_mapobjs, 6 * mapobj_count), "geometry": (offset, 28)}
    end = max(o + n for o, n in regions.values())
    if end > len(image):
        raise GeometryError("geometry arrays run past the end of the file")
    return RawGeometry(yakumono_count, vertices, ids, links, info, mapobjs, regions,
                       {"geometry_offset": offset, "pointer_decode": "intern chain" if intern is not None else "low 16 bits"})


def parse_header_image(image: bytes) -> Dict[str, int]:
    if len(image) < 0x8A:
        raise GeometryError("map header too short")
    return {k: int.from_bytes(image[o:o + 2], "big", signed=True) for k, o in HEADER_FIELDS_S16.items()}


# -- ROM ---------------------------------------------------------------------------------------------------


def normalise_rom(rom: bytes) -> Tuple[bytes, str]:
    head = rom[:4]
    if head == b"\x80\x37\x12\x40":
        return rom, "z64"
    if head == b"\x37\x80\x40\x12":
        b = bytearray(rom)
        b[0::2], b[1::2] = rom[1::2], rom[0::2]
        return bytes(b), "v64"
    if head == b"\x40\x12\x37\x80":
        b = bytearray(len(rom))
        for i in range(0, len(rom) - 3, 4):
            b[i:i + 4] = rom[i:i + 4][::-1]
        return bytes(b), "n64"
    raise GeometryError("not an N64 ROM image (unknown first word)")


def rom_region(rom: bytes) -> Optional[str]:
    code = rom[0x3B:0x3F]
    if code == b"NALE":
        return "us"
    if code == b"NALJ":
        return "jp"
    return None


@dataclass
class RelocFile:
    file_id: int
    rom_offset: int
    rom_size: int
    compressed: bool
    compressed_words: int
    decompressed_words: int
    intern_start: int
    extern_start: int
    image: bytes = b""
    vpk0_method: Optional[int] = None
    extern_ids: List[int] = field(default_factory=list)


class Rom:
    def __init__(self, data: bytes, version: Optional[str] = None) -> None:
        self.data, self.byte_order = normalise_rom(data)
        detected = rom_region(self.data)
        self.version = version or detected
        if self.version not in VERSIONS:
            raise GeometryError(f"unknown ROM version (header code {self.data[0x3B:0x3F]!r}); pass --version us|jp")
        self.detected_version = detected
        cfg = VERSIONS[self.version]
        self.table = cfg["reloc_table"]
        self.count = cfg["file_count"]
        self.data_start = self.table + (self.count + 1) * RELOC_ENTRY.size

    def entry(self, file_id: int) -> Tuple[int, int, int, int, int]:
        if not 0 <= file_id < self.count:
            raise GeometryError(f"file id {file_id} outside the table")
        o = self.table + RELOC_ENTRY.size * file_id
        return RELOC_ENTRY.unpack_from(self.data, o)

    def file(self, file_id: int) -> RelocFile:
        first, intern, comp_words, extern, decomp_words = self.entry(file_id)
        nxt = RELOC_ENTRY.unpack_from(self.data, self.table + RELOC_ENTRY.size * (file_id + 1))[0]
        off = first & 0x7FFFFFFF
        size = (nxt & 0x7FFFFFFF) - off
        rom_off = self.data_start + off
        if size <= 0 or rom_off + size > len(self.data):
            raise GeometryError(f"file {file_id}: bad extent (offset 0x{rom_off:X}, size {size})")
        blob = self.data[rom_off:rom_off + size]
        rf = RelocFile(file_id, rom_off, size, bool(first & 0x80000000), comp_words, decomp_words, intern, extern)
        if rf.compressed:
            rf.image, rf.vpk0_method = vpk0.decode(blob)[:decomp_words * 4], blob[8]
        else:
            rf.image = blob[:decomp_words * 4]
        if len(rf.image) != decomp_words * 4:
            raise GeometryError(f"file {file_id}: decoded {len(rf.image)} bytes, table says {decomp_words * 4}")
        n_ext = len(chain_map(rf.image, extern))
        trailer = self.data[rom_off + comp_words * 4: rom_off + comp_words * 4 + 2 * n_ext]
        rf.extern_ids = [int.from_bytes(trailer[2 * i:2 * i + 2], "big") for i in range(n_ext)]
        return rf


def yaml_file_entries(repo_root: Path, version: str) -> Dict[int, Dict[str, Any]]:
    """file_id -> {symbol, offset, size} from the port's own asset yamls (yamls/<version>/*.yml), if present."""
    out: Dict[int, Dict[str, Any]] = {}
    d = repo_root / "yamls" / version
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.yml")):
        cur: Dict[str, Any] = {}
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^([A-Za-z0-9_]+):\s*$", raw)
            if m:
                cur = {"symbol": m.group(1)}
                continue
            m = re.match(r"^\s+(offset|size|file_id):\s*(0x[0-9A-Fa-f]+|\d+)\s*$", raw)
            if m and cur:
                cur[m.group(1)] = int(m.group(2), 0)
                if "file_id" in cur and "offset" in cur and "size" in cur:
                    out[cur["file_id"]] = dict(cur)
    return out


def extract_from_rom(rom_bytes: bytes, version: Optional[str] = None, repo_root: Optional[Path] = None,
                     header_file: Optional[int] = None) -> Tuple[Geometry, Dict[str, Any]]:
    """Locate the Mario Break-the-Targets map header, follow its map_geometry pointer and parse the geometry.
    Returns the geometry and a report of every cross-check made."""
    rom = Rom(rom_bytes, version)
    report: Dict[str, Any] = {"byte_order": rom.byte_order, "version": rom.version, "detected_version": rom.detected_version,
                              "reloc_table": f"0x{rom.table:X}", "checks": []}
    yaml = yaml_file_entries(repo_root, rom.version) if repo_root else {}
    hid = header_file if header_file is not None else VERSIONS[rom.version]["header_file"]
    if hid < 0:
        hits = [fid for fid, e in yaml.items() if e.get("symbol") == HEADER_SYMBOL]
        if len(hits) != 1:
            raise GeometryError(f"cannot find {HEADER_SYMBOL} in yamls/{rom.version}; pass --header-file")
        hid = hits[0]
    header = rom.file(hid)
    ext = chain_map(header.image, header.extern_start)
    slots = list(ext)
    if HEADER_MAP_GEOMETRY_SLOT not in ext:
        raise GeometryError(f"file {hid}: map_geometry (0x{HEADER_MAP_GEOMETRY_SLOT:X}) is not an extern pointer")
    k = slots.index(HEADER_MAP_GEOMETRY_SLOT)
    gid, goff = header.extern_ids[k], ext[HEADER_MAP_GEOMETRY_SLOT]
    gfile = rom.file(gid)
    intern = chain_map(gfile.image, gfile.intern_start)
    raw = parse_geometry_image(gfile.image, goff, intern)
    raw.header = parse_header_image(header.image)
    raw.source = dict(raw.source, rom_version=rom.version, header_file=hid, geometry_file=gid,
                      geometry_file_rom_offset=gfile.rom_offset, geometry_file_bytes=len(gfile.image),
                      vpk0_method=gfile.vpk0_method)
    for f in (header, gfile):
        e = yaml.get(f.file_id)
        if e:
            ok = e["offset"] == f.rom_offset
            report["checks"].append({"check": f"yamls/{rom.version} offset of file {f.file_id} ({e['symbol']})",
                                     "ok": ok, "yaml": f"0x{e['offset']:X}", "table": f"0x{f.rom_offset:X}"})
    report["header_file"], report["geometry_file"], report["geometry_offset"] = hid, gid, f"0x{goff:X}"
    geo = derive(raw, origin=f"rom:{rom.version}")
    return geo, report


# -- decomp source (no ROM) -----------------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _initializer(text: str, symbol: str) -> str:
    m = re.search(r"\b" + re.escape(symbol) + r"\s*(\[[^\]]*\])?\s*=\s*\{", text)
    if not m:
        raise GeometryError(f"symbol {symbol} not found in the decomp source")
    i, depth = m.end() - 1, 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    raise GeometryError(f"unterminated initializer for {symbol}")


def _ints(s: str) -> List[int]:
    return [int(t, 0) for t in re.findall(r"-?(?:0x[0-9A-Fa-f]+|\d+)", s)]


def _block_offset(text: str, symbol: str) -> Optional[int]:
    m = re.search(r"@\s*(0x[0-9A-Fa-f]+)[^\n]*\n[^\n]*\b" + re.escape(symbol) + r"\b", text)
    return int(m.group(1), 16) if m else None


def parse_decomp_source(stage_c: Path, header_c: Optional[Path] = None) -> RawGeometry:
    """Decode the geometry from the decomp's relocData C source (e.g. decomp/src/relocData/124_GRBonus1MarioFile2.c)."""
    raw_text = stage_c.read_text(encoding="utf-8")
    text = _strip_comments(raw_text)
    m = re.search(r"MPGeometryData\s+(\w+)\s*=\s*\{", text)
    if not m:
        raise GeometryError(f"no MPGeometryData in {stage_c}")
    body = _initializer(text, m.group(1))
    parts = [p.strip() for p in body.split(",") if p.strip()]
    if len(parts) != 7:
        raise GeometryError(f"unexpected MPGeometryData initializer: {parts}")

    def sym(p: str) -> str:
        return re.sub(r"^\([^)]*\)\s*", "", p).lstrip("&").strip()

    yakumono_count = int(parts[0], 0)
    s_vertex, s_ids, s_links, s_info, s_mapobjs = sym(parts[1]), sym(parts[2]), sym(parts[3]), sym(parts[4]), sym(parts[6])
    mapobj_count = int(parts[5], 0)
    v = _ints(_initializer(text, s_vertex))
    vertices = [Vertex(v[i], v[i + 1], v[i + 2]) for i in range(0, len(v), 3)]
    ids = _ints(_initializer(text, s_ids))
    lk = _ints(_initializer(text, s_links))
    links = [(lk[i], lk[i + 1]) for i in range(0, len(lk), 2)]
    li = _ints(_initializer(text, s_info))
    if len(li) != 9 * yakumono_count:
        raise GeometryError("MPLineInfo initializer does not match yakumono_count")
    info = [LineInfo(li[9 * i], [(li[9 * i + 1 + 2 * k], li[9 * i + 2 + 2 * k]) for k in range(4)]) for i in range(yakumono_count)]
    mo = _ints(_initializer(text, s_mapobjs))
    mapobjs = [(mo[i], mo[i + 1], mo[i + 2]) for i in range(0, len(mo), 3)][:mapobj_count]
    regions: Dict[str, Tuple[int, int]] = {}
    for name, s, nbytes in (("vertex_data", s_vertex, 6 * len(vertices)), ("vertex_id", s_ids, 2 * len(ids)),
                            ("vertex_links", s_links, 4 * len(links)), ("line_info", s_info, 18 * yakumono_count),
                            ("mapobjs", s_mapobjs, 6 * mapobj_count), ("geometry", m.group(1), 28)):
        off = _block_offset(raw_text, s)
        if off is not None:
            regions[name] = (off, nbytes)
    raw = RawGeometry(yakumono_count, vertices, ids, links, info, mapobjs, regions,
                      {"decomp_source": str(stage_c), "geometry_symbol": m.group(1)})
    if header_c is not None and header_c.exists():
        htext = header_c.read_text(encoding="utf-8")
        for key in HEADER_FIELDS_S16:
            hm = re.search(r"(-?\d+)\s*,\s*/\*\s*" + key + r"\s*\*/", htext)
            if hm:
                raw.header[key] = int(hm.group(1))
    return raw


def to_file_image(raw: RawGeometry, size: int, geometry_offset: int) -> Tuple[bytes, int]:
    """Serialise RawGeometry into an N64-layout file image with chain-encoded pointer slots, using the region
    offsets recorded in raw.regions. Returns (image, intern chain start word). Test helper."""
    img = bytearray(size)
    r = raw.regions

    def put16(o: int, val: int, signed: bool = False) -> None:
        img[o:o + 2] = int(val).to_bytes(2, "big", signed=signed)

    for i, vx in enumerate(raw.vertices):
        o = r["vertex_data"][0] + 6 * i
        put16(o, vx.x, True)
        put16(o + 2, vx.y, True)
        put16(o + 4, vx.flags)
    for i, vid in enumerate(raw.vertex_ids):
        put16(r["vertex_id"][0] + 2 * i, vid)
    for i, (a, b) in enumerate(raw.links):
        put16(r["vertex_links"][0] + 4 * i, a)
        put16(r["vertex_links"][0] + 4 * i + 2, b)
    for i, li in enumerate(raw.line_info):
        o = r["line_info"][0] + 18 * i
        put16(o, li.yakumono_id)
        for k, (g, c) in enumerate(li.data):
            put16(o + 2 + 4 * k, g)
            put16(o + 4 + 4 * k, c)
    for i, (kind, x, y) in enumerate(raw.mapobjs):
        o = r["mapobjs"][0] + 6 * i
        put16(o, kind)
        put16(o + 2, x, True)
        put16(o + 4, y, True)
    put16(geometry_offset, raw.yakumono_count)
    put16(geometry_offset + 20, len(raw.mapobjs))
    slots = [(geometry_offset + 4, r["vertex_data"][0]), (geometry_offset + 8, r["vertex_id"][0]),
             (geometry_offset + 12, r["vertex_links"][0]), (geometry_offset + 16, r["line_info"][0]),
             (geometry_offset + 24, r["mapobjs"][0])]
    for i, (slot, target) in enumerate(slots):
        nxt = slots[i + 1][0] // 4 if i + 1 < len(slots) else 0xFFFF
        img[slot:slot + 4] = ((nxt << 16) | (target // 4)).to_bytes(4, "big")
    return bytes(img), slots[0][0] // 4


# -- traces (what the port actually loaded) --------------------------------------------------------------------


def open_json(path: Path) -> Any:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        return json.load(f)


def lines_from_trace_reply(reply: Mapping[str, Any]) -> Geometry:
    """Geometry from an observe reply's btt_spatial_v1 `lines` (the table the native game loaded).
    Only the first vertex's flags are recorded natively; they are repeated for every vertex here."""
    sp = reply.get("spatial") or {}
    rows = sp.get("lines")
    if not rows:
        raise GeometryError("the reply has no spatial.lines (observe replies with SSB64_RL_SPATIAL=1 carry them)")
    lines: List[Line] = []
    for row in rows:
        pts = [(float(p[0]), float(p[1])) for p in row["vertices"]]
        kind = int(row["type"])
        use_y = kind < 2
        vals = [p[1] if use_y else p[0] for p in pts]
        flags = int(row.get("flags", 0))
        lines.append(Line(id=int(row["id"]), kind=kind, group=int(row["group"]), group_seq=int(row["group"]),
                          vertex_index=[], points=pts, vflags=[flags] * len(pts), coll_near=int(min(vals)),
                          coll_far=int(max(vals))))
    _coordinate_edges(lines)
    header = {}
    mb, cb = sp.get("map_bounds"), sp.get("camera_bounds")
    if mb:
        header.update(map_bound_top=mb[0], map_bound_bottom=mb[1], map_bound_right=mb[2], map_bound_left=mb[3])
    if cb:
        header.update(camera_bound_top=cb[0], camera_bound_bottom=cb[1], camera_bound_right=cb[2], camera_bound_left=cb[3])
    return Geometry(lines=lines, origin="trace", header=header,
                    notes=["edges matched by coordinates (the trace has no vertex indices)",
                           "per-segment flags not recorded natively: the first vertex's flags are used for every segment"])


def _coordinate_edges(lines: List[Line]) -> None:
    for line in lines:
        a, b = line.points[0], line.points[-1]
        prev_id = next_id = -1
        for other in lines:
            if other.id == line.id:
                continue
            ends = (other.points[0], other.points[-1])
            if a in ends:
                prev_id = other.id
            if b in ends:
                next_id = other.id
        swap = (b[0] < a[0]) if line.kind in (KIND_FLOOR, KIND_CEIL) else (b[1] < a[1])
        line.edge_next, line.edge_prev = (prev_id, next_id) if swap else (next_id, prev_id)


def load_geometry_json(path: Path) -> Geometry:
    data = open_json(path)
    if data.get("schema") != SCHEMA:
        raise GeometryError(f"{path}: not a {SCHEMA} file")
    lines = [Line(id=r["id"], kind=r["type"], group=r["group"], group_seq=r.get("group_seq", r["group"]),
                  vertex_index=r.get("vertex_index", []), points=[(float(p[0]), float(p[1])) for p in r["points"]],
                  vflags=list(r["vertex_flags"]), coll_near=r["coll_pos"][0], coll_far=r["coll_pos"][1],
                  edge_next=r["edge_next"], edge_prev=r["edge_prev"]) for r in data["lines"]]
    g = Geometry(lines=lines, origin=data.get("origin", str(path)), header=dict(data.get("header") or {}),
                 notes=list(data.get("notes") or []))
    raw = data.get("raw")
    if raw:
        g.raw = RawGeometry(raw["yakumono_count"], [Vertex(*v) for v in raw["vertices"]], list(raw["vertex_ids"]),
                            [tuple(k) for k in raw["links"]], [LineInfo(a, [tuple(d) for d in b]) for a, b in raw["line_info"]],
                            [tuple(m) for m in raw["mapobjs"]], {k: tuple(v) for k, v in raw.get("regions", {}).items()},
                            dict(raw.get("source") or {}), dict(g.header))
    return g


def compare_lines(a: Geometry, b: Geometry) -> List[str]:
    """Differences between two line tables (e.g. ROM extraction against a trace's native table)."""
    diffs: List[str] = []
    if len(a.lines) != len(b.lines):
        diffs.append(f"line count {len(a.lines)} != {len(b.lines)}")
    for la, lb in zip(a.lines, b.lines):
        if la.kind != lb.kind:
            diffs.append(f"line {la.id}: kind {la.kind_name} != {lb.kind_name}")
        if la.group != lb.group:
            diffs.append(f"line {la.id}: group {la.group} != {lb.group}")
        if [tuple(p) for p in la.points] != [tuple(p) for p in lb.points]:
            diffs.append(f"line {la.id}: vertices {la.points} != {lb.points}")
        if la.flags_first != lb.flags_first:
            diffs.append(f"line {la.id}: first-vertex flags 0x{la.flags_first:04X} != 0x{lb.flags_first:04X}")
    return diffs


def default_decomp_paths(repo_root: Path) -> Tuple[Path, Path]:
    base = repo_root / "decomp" / "src" / "relocData"
    return base / "124_GRBonus1MarioFile2.c", base / "271_GRBonus1MarioMap.c"


def mario_ecb_from_decomp(repo_root: Path) -> Optional[Tuple[float, float, float, float]]:
    """FTAttributes.map_coll (top, center, bottom, width) of Mario from decomp/src/relocData/203_MarioMain.c."""
    p = repo_root / "decomp" / "src" / "relocData" / "203_MarioMain.c"
    if not p.exists():
        return None
    m = re.search(r"\{\s*([-\d.]+)f?\s*,\s*([-\d.]+)f?\s*,\s*([-\d.]+)f?\s*,\s*([-\d.]+)f?\s*\}\s*,\s*/\*\s*map_coll\s*\*/",
                  p.read_text(encoding="utf-8"))
    return tuple(float(m.group(i)) for i in range(1, 5)) if m else None  # type: ignore[return-value]
