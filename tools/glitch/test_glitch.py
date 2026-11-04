#!/usr/bin/env python3
"""Tests for tools/glitch (no ROM, no game). Run: python -I tools/glitch/test_glitch.py

What they cover:
  - vpk0: round trip through the test encoder for both sample methods; the same streams through torch's C decoder
    (torch/lib/libvpk0/vpk0.c, compiled with cc if available, else skipped);
  - ROM path: a synthetic ROM (z64, v64 and n64 byte orders) built from the decomp-source geometry, with a reloc table at
    the US address, file 124 vpk0-compressed with an intern chain, and the map header with an extern chain + file-id
    trailer; extraction must reproduce the decomp decode exactly;
  - analysis: each check on crafted geometry where the answer is known (unsorted lines, wrong running index, misaligned
    PORT region, short floor, narrow passage, thin solid, moving band, target behind a wall);
  - detector: synthetic traces for each event kind, and no event on a clean trace.
What they do not cover: the real ROM's bytes, the real trace files, MSVC behaviour.
"""

from __future__ import annotations

import ctypes
import gzip
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analysis  # noqa: E402
import detect  # noqa: E402
import geometry as gm  # noqa: E402
import glitch  # noqa: E402
import vpk0  # noqa: E402

REPO = HERE.parent.parent
STAGE_C, HEADER_C = gm.default_decomp_paths(REPO)
HAVE_DECOMP = STAGE_C.exists()
ECB = analysis.Ecb(320.0, 190.0, 0.0, 150.0)


def _cc() -> str:
    for c in ("cc", "gcc", "clang"):
        if shutil.which(c):
            return c
    return ""


class Vpk0Tests(unittest.TestCase):
    def samples(self):
        rnd = random.Random(1234)
        yield b"a"
        yield bytes(range(256)) * 3
        yield b"abcabcabcabcabcabcabcabcxyz" * 40
        yield bytes(rnd.randrange(4) for _ in range(5000))
        yield bytes(rnd.randrange(256) for _ in range(3000))
        yield (b"\x00\x00\x01\x2c" * 300) + bytes(rnd.randrange(256) for _ in range(77))

    def test_round_trip_both_methods(self):
        for data in self.samples():
            for method in (0, 1):
                enc = vpk0.encode(data, method=method)
                self.assertEqual(vpk0.decoded_size(enc), len(data))
                self.assertEqual(vpk0.decode(enc), data, f"method {method}, {len(data)} bytes")

    def test_compresses_repetitive_input(self):
        data = b"\x00\x01\x02\x03" * 1000
        self.assertLess(len(vpk0.encode(data, 1)), len(data) // 4)

    def test_bad_magic(self):
        with self.assertRaises(vpk0.VPK0Error):
            vpk0.decode(b"vpk1\x00\x00\x00\x04\x00")

    def test_against_c_reference(self):
        src = REPO / "torch" / "lib" / "libvpk0" / "vpk0.c"
        cc = _cc()
        if not src.exists() or not cc:
            self.skipTest("torch submodule or C compiler not available")
        tmp = Path(tempfile.mkdtemp(prefix="vpk0ref_"))
        try:
            lib = tmp / "libvpk0ref.so"
            subprocess.run([cc, "-O2", "-shared", "-fPIC", "-o", str(lib), str(src)], check=True, capture_output=True)
            ref = ctypes.CDLL(str(lib))
            ref.vpk0_decode.restype = ctypes.c_uint32
            ref.vpk0_decode.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
            for data in self.samples():
                for method in (0, 1):
                    enc = vpk0.encode(data, method=method)
                    out = ctypes.create_string_buffer(len(data) + 64)
                    n = ref.vpk0_decode(enc, len(enc), out, len(data) + 64)
                    self.assertEqual(n, len(data))
                    self.assertEqual(out.raw[:n], data, f"C reference disagrees (method {method})")
                    self.assertEqual(vpk0.decode(enc), out.raw[:n])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def build_synthetic_rom(raw: gm.RawGeometry, header: dict, version: str = "us", geo_file: int = 124,
                        header_file: int = 271, method: int = 1) -> bytes:
    """A ROM image with only what extraction reads: header code, reloc table, file 124 and the map header file."""
    cfg = gm.VERSIONS[version]
    count = cfg["file_count"]
    table = cfg["reloc_table"]
    data_start = table + (count + 1) * 12
    geo_off = raw.regions["geometry"][0]
    image, intern = gm.to_file_image(raw, 0x23C0, geo_off)
    # map header file: 0xB0 bytes, map_geometry extern slot at 0x40, a second extern slot at 0x48 (wallpaper)
    himg = bytearray(0xB0)
    himg[0x40:0x44] = ((0x48 // 4 << 16) | (geo_off // 4)).to_bytes(4, "big")
    himg[0x48:0x4C] = ((0xFFFF << 16) | 0x1234).to_bytes(4, "big")
    for k, o in gm.HEADER_FIELDS_S16.items():
        himg[o:o + 2] = int(header.get(k, 0)).to_bytes(2, "big", signed=True)
    files = {}
    for fid, img, intern_start, extern_start, trailer in (
            (geo_file, image, intern, 0xFFFF, b""),
            (header_file, bytes(himg), 0xFFFF, 0x40 // 4, (geo_file).to_bytes(2, "big") + (77).to_bytes(2, "big"))):
        blob = vpk0.encode(img, method=method)
        blob += b"\x00" * (-len(blob) % 4)
        files[fid] = (blob + trailer, len(blob) // 4, intern_start, extern_start, len(img) // 4)
    rom = bytearray(data_start)
    rom[0:4] = b"\x80\x37\x12\x40"
    rom[0x3B:0x3F] = b"NALE" if version == "us" else b"NALJ"
    offsets = {}
    for fid in sorted(files):
        while len(rom) % 2:
            rom.append(0)
        offsets[fid] = len(rom) - data_start
        rom += files[fid][0]
    end = len(rom) - data_start
    for fid in range(count + 1):
        if fid in files:
            blob, cw, i0, e0, dw = files[fid]
            entry = gm.RELOC_ENTRY.pack(0x80000000 | offsets[fid], i0, cw, e0, dw)
        else:
            nxt = min([o for f, o in offsets.items() if f > fid] + [end])
            entry = gm.RELOC_ENTRY.pack(nxt, 0xFFFF, 0, 0xFFFF, 0)
        rom[table + 12 * fid: table + 12 * fid + 12] = entry
    rom += b"\x00" * (-len(rom) % 4)
    return bytes(rom)


@unittest.skipUnless(HAVE_DECOMP, "decomp submodule not checked out")
class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.raw = gm.parse_decomp_source(STAGE_C, HEADER_C)
        self.ref = gm.derive(self.raw, "decomp-source")

    def test_decomp_decode_is_self_consistent(self):
        self.assertEqual(self.raw.regions["geometry"], (0x20E8, 28))
        kinds = [l.kind for l in self.ref.lines]
        self.assertEqual(len(kinds), sum(c for li in self.raw.line_info for _, c in li.data))
        for l in self.ref.lines:
            self.assertEqual(l.group, l.group_seq)
        self.assertIn("map_bound_bottom", self.raw.header)

    def test_matches_the_m7g_fixture_line_table(self):
        fx = REPO / "rl" / "fixtures" / "m7g" / "upper_moving_platform_8b9ecf2b967f.json"
        if not fx.exists():
            self.skipTest("m7g fixture not present")
        rows = json.loads(fx.read_text())["geometry"]["lines"]
        names = {"floor": 0, "ceil": 1, "rwall": 2, "lwall": 3}
        self.assertEqual(len(rows), len(self.ref.lines))
        for row, l in zip(rows, self.ref.lines):
            self.assertEqual(names[row["kind"]], l.kind)
            self.assertEqual(row["group"], l.group)
            self.assertEqual([tuple(p) for p in row["points"]], l.points)
            self.assertEqual(row["flags"], l.flags_first)

    def _extract(self, rom: bytes, **kw):
        return gm.extract_from_rom(rom, repo_root=None, **kw)

    def test_synthetic_rom_round_trip(self):
        for method in (0, 1):
            rom = build_synthetic_rom(self.raw, self.raw.header, method=method)
            geo, report = self._extract(rom)
            self.assertEqual(report["version"], "us")
            self.assertEqual(report["geometry_file"], 124)
            self.assertEqual(report["geometry_offset"], "0x20E8")
            self.assertEqual(gm.compare_lines(geo, self.ref), [])
            self.assertEqual(geo.sha256(), self.ref.sha256())
            self.assertEqual([(v.x, v.y, v.flags) for v in geo.raw.vertices], [(v.x, v.y, v.flags) for v in self.raw.vertices])
            self.assertEqual(geo.header, {k: self.raw.header[k] for k in gm.HEADER_FIELDS_S16 if k in self.raw.header})
            self.assertEqual(geo.raw.regions["vertex_data"], self.raw.regions["vertex_data"])

    def test_byte_orders(self):
        rom = build_synthetic_rom(self.raw, self.raw.header)
        v64 = bytearray(rom)
        v64[0::2], v64[1::2] = rom[1::2], rom[0::2]
        n64 = bytearray(len(rom))
        for i in range(0, len(rom), 4):
            n64[i:i + 4] = rom[i:i + 4][::-1]
        for img, name in ((bytes(v64), "v64"), (bytes(n64), "n64")):
            geo, report = self._extract(img)
            self.assertEqual(report["byte_order"], name)
            self.assertEqual(geo.sha256(), self.ref.sha256())

    def test_pointer_off_chain_is_refused(self):
        geo_off = self.raw.regions["geometry"][0]
        image, intern = gm.to_file_image(self.raw, 0x23C0, geo_off)
        chain = gm.chain_map(image, intern)
        self.assertEqual(sorted(chain), [geo_off + o for o in (4, 8, 12, 16, 24)])
        chain.pop(geo_off + 12)
        with self.assertRaises(gm.GeometryError):
            gm.parse_geometry_image(image, geo_off, chain)

    def test_cli_extract_and_compare(self):
        tmp = Path(tempfile.mkdtemp(prefix="glitch_cli_"))
        try:
            rom = tmp / "synthetic.z64"
            rom.write_bytes(build_synthetic_rom(self.raw, self.raw.header))
            out = tmp / "geo.json"
            self.assertEqual(glitch.main(["extract", "--rom", str(rom), "--out", str(out)]), 1)  # yaml offsets differ
            self.assertEqual(glitch.main(["extract", "--rom", str(rom), "--out", str(out), "--no-yaml-check"]), 0)
            data = json.loads(out.read_text())
            self.assertTrue(all(c["ok"] for c in data["extraction_report"]["checks"]))
            trace = make_trace(self.ref, [(0.0, 300.0, 0)] * 3)
            tp = tmp / "t.json.gz"
            with gzip.open(tp, "wt") as f:
                json.dump(trace, f)
            self.assertEqual(glitch.main(["compare", "--geometry", str(out), "--trace", str(tp)]), 0)
            trace["initial"]["spatial"]["lines"][3]["vertices"][0][0] += 1
            with gzip.open(tp, "wt") as f:
                json.dump(trace, f)
            self.assertEqual(glitch.main(["compare", "--geometry", str(out), "--trace", str(tp)]), 1)
            self.assertEqual(glitch.main(["analyze", "--geometry", str(out), "--out", str(tmp / "cand")]), 0)
            self.assertTrue((tmp / "cand.md").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_port_swap_absent_on_decomp_layout(self):
        f = analysis.check_port_swap(self.ref)
        self.assertEqual([x.status for x in f], ["absent"])


# -- crafted geometry ------------------------------------------------------------------------------------------------


def raw_from_lines(spec, groups=None):
    """spec: list of (kind, [(x, y), ...], flags) in line-id order; lines are grouped by (group, kind) runs."""
    vertices, ids, links = [], [], []
    for kind, pts, flags in spec:
        links.append((len(ids), len(pts)))
        for x, y in pts:
            ids.append(len(vertices))
            vertices.append(gm.Vertex(int(x), int(y), flags))
    groups = groups or [1] * len(spec)
    info = []
    i = 0
    order = []
    while i < len(spec):
        g = groups[i]
        data = [(i, 0)] * 4
        j = i
        cur = []
        while j < len(spec) and groups[j] == g:
            cur.append(j)
            j += 1
        for kind in range(4):
            ks = [k for k in cur if spec[k][0] == kind]
            data[kind] = (ks[0], len(ks)) if ks else (cur[-1] + 1, 0)
        info.append(gm.LineInfo(g, data))
        i = j
    return gm.RawGeometry(len(info), vertices, ids, links, info, [], {}, {})


def box(x0, y0, x1, y1):
    """A solid rectangle as four lines (floor on top, ceiling below, walls) sharing coordinates (not vertex ids)."""
    return [(gm.KIND_FLOOR, [(x0, y1), (x1, y1)], 0), (gm.KIND_CEIL, [(x1, y0), (x0, y0)], 0),
            (gm.KIND_RWALL, [(x1, y1), (x1, y0)], 0), (gm.KIND_LWALL, [(x0, y0), (x0, y1)], 0)]


def sorted_spec(spec):
    return sorted(spec, key=lambda s: s[0])


class AnalysisTests(unittest.TestCase):
    def geo(self, spec, groups=None):
        return gm.derive(raw_from_lines(spec, groups), "test")

    def test_sweep_order_detects_unsorted_floors(self):
        spec = [(0, [(0, 0), (100, 0)], 0), (0, [(0, 500), (100, 500)], 0)]
        f = analysis.check_sweep_order(self.geo(spec))
        self.assertEqual(f[0].status, "present")
        self.assertEqual(f[0].where["lines"], [0, 1])
        ok = analysis.check_sweep_order(self.geo(list(reversed(spec))))
        self.assertEqual(ok[0].status, "absent")

    def test_sweep_order_ceil_and_walls(self):
        spec = [(1, [(100, 500), (0, 500)], 0), (1, [(100, 0), (0, 0)], 0)]
        self.assertEqual(analysis.check_sweep_order(self.geo(spec))[0].status, "present")
        spec = [(2, [(0, 100), (0, 0)], 0), (2, [(500, 100), (500, 0)], 0)]
        self.assertEqual(analysis.check_sweep_order(self.geo(spec))[0].status, "present")
        spec = [(3, [(500, 0), (500, 100)], 0), (3, [(0, 0), (0, 100)], 0)]
        self.assertEqual(analysis.check_sweep_order(self.geo(spec))[0].status, "present")

    def test_running_index_mismatch(self):
        raw = raw_from_lines([(0, [(0, 0), (100, 0)], 0), (1, [(100, -50), (0, -50)], 0)])
        raw.line_info = [gm.LineInfo(1, [(1, 1), (0, 1), (2, 0), (2, 0)])]  # floor listed at id 1, ceil at id 0
        raw.links = [raw.links[1], raw.links[0]]
        geo = gm.derive(raw, "test")
        f = analysis.check_running_index(geo)
        self.assertTrue(any(x.status == "present" for x in f))

    def test_port_swap_misaligned(self):
        geo = self.geo([(0, [(0, 0), (100, 0)], 0)])
        geo.raw.regions = {"vertex_data": (0x100, 6 * 5), "vertex_id": (0x11E, 4), "geometry": (0x200, 28)}
        f = analysis.check_port_swap(geo)
        self.assertTrue(any("not word-aligned" in x.detail for x in f))
        self.assertTrue(any("rotated twice" in x.detail for x in f))

    def test_short_floor(self):
        f = analysis.check_short_floors(self.geo([(0, [(0, 0), (30, 0)], 0)]))
        self.assertEqual(f[0].status, "present")

    def test_degenerate(self):
        f = analysis.check_degenerate(self.geo([(0, [(0, 0), (0, 10)], 0)]))
        self.assertEqual(f[0].status, "present")

    def test_narrow_passage_and_thin_solid(self):
        spec = sorted_spec(box(-1000, -100, -100, 0) + box(150, -100, 1000, 0) + box(-50, 500, 50, 1500))
        geo = self.geo(spec)
        f = analysis.check_passages_and_thickness(geo, ECB)
        gaps = [x for x in f if x.check == "narrow_passage" and x.status == "present"]
        self.assertTrue(any(abs(x.where["gap"] - 250) < 1e-6 for x in gaps), [x.detail for x in f])
        thin = [x for x in f if x.check == "thin_solid" and x.status == "present"]
        self.assertTrue(any(abs(x.where["thickness"] - 100) < 1e-6 and x.where["axis"] == "x" for x in thin))
        self.assertTrue(any(abs(x.where["thickness"] - 100) < 1e-6 and x.where["axis"] == "y" for x in thin))

    def test_low_clearance(self):
        spec = sorted_spec(box(-1000, -100, 1000, 0) + box(-1000, 200, 1000, 400))
        f = analysis.check_passages_and_thickness(self.geo(spec), ECB)
        low = [x for x in f if x.check == "low_clearance" and x.status == "present"]
        self.assertTrue(low and abs(low[0].where["gap"] - 200) < 1e-6 and low[0].mechanism == "M4")

    def test_loops_and_inside(self):
        geo = self.geo(sorted_spec(box(0, 0, 100, 100)))
        lps = analysis.loops(geo)
        self.assertEqual(len(lps), 1)
        self.assertTrue(lps[0].solid_inside)
        self.assertIsNotNone(analysis.inside_solid((50, 50), lps))
        self.assertIsNone(analysis.inside_solid((150, 50), lps))

    def test_corners(self):
        geo = self.geo(sorted_spec(box(0, 0, 100, 100)))
        f = analysis.check_connectivity(geo)
        convex = [x for x in f if x.check == "corner" and x.where.get("corner") == "convex"]
        self.assertEqual(len(convex), 4)
        unlinked = [x for x in f if x.check == "unlinked_touch"]
        self.assertEqual(len(unlinked), 4)  # the crafted box joins by coordinates, not shared vertex ids

    def test_moving_band(self):
        spec = [(0, [(-100, 0), (100, 0)], gm.VERTEX_COLL_PASS), (1, [(100, 2000), (-100, 2000)], 0)]
        geo = self.geo(spec, groups=[2, 1])
        f = analysis.check_moving_band(geo, ECB, {2: (0.0, 0.0, 0.0, 1800.0)})
        self.assertEqual(f[0].status, "present")
        f = analysis.check_moving_band(geo, ECB, {2: (0.0, 0.0, 0.0, 1000.0)})
        self.assertEqual(f[0].status, "absent")

    def test_target_behind_line(self):
        geo = self.geo(sorted_spec(box(0, 0, 100, 1000)))
        lps = analysis.loops(geo)
        f = analysis.check_targets(geo, [(0, 300, 500, False), (1, 3000, 500, False)], 150, 100, lps)
        self.assertEqual([x.where["target"] for x in f if x.status == "present"], [0])

    @unittest.skipUnless(HAVE_DECOMP, "decomp submodule not checked out")
    def test_runs_on_decomp_geometry(self):
        geo = gm.derive(gm.parse_decomp_source(STAGE_C, HEADER_C), "decomp-source")
        r = analysis.run_all(geo, ECB)
        self.assertEqual(r["summary"]["sweep_order"], {"absent": 1})
        self.assertEqual(r["summary"]["running_index"], {"absent": 1})
        self.assertTrue(analysis.to_markdown(r).startswith("# Glitch geometry candidates"))


# -- synthetic traces ---------------------------------------------------------------------------------------------------


def make_trace(geo, path, groups=None, extra=None):
    """path: list of (x, y, ga) per tick (the first is the initial observe reply). extra: per-index dict merged in."""
    lines = [{"id": l.id, "type": l.kind, "group": l.group, "flags": l.flags_first, "vertex_total": len(l.points),
              "vertices": [list(p) for p in l.points]} for l in geo.lines]

    def reply(i, x, y, ga, vx, vy):
        r = {"consumed_tick": i - 1 if i else None,
             "observation": {"position_x": x, "position_y": y, "air_velocity_x": vx, "air_velocity_y": vy,
                             "ground_air_state": ga, "fighter_status_id": 10, "fighter_valid": 1, "btt_active": 1,
                             "input_tick": i},
             "spatial": {"fighter": {"floor_line_id": -1, "lwall_line_id": -1, "rwall_line_id": -1, "ceil_line_id": -1,
                                     "mask_curr": 0, "carry": [0, 0], "coll": [320, 190, 0, 150]},
                         "groups": groups[i] if groups else [], "map_bounds": [9600, -9600, 9600, -9600],
                         "camera_bounds": [5000, -5000, 5000, -5000], "target_live_mask": 1,
                         "target_positions": [[5000, 5000]]},
             "entity": {"fighter": {"hitlag_tics": 0, "attack_active": 0}, "weapons": []},
             "input": {"stick_x": 0}, "targets": {"remaining_mask": 1, "records": [{"id": 0, "spawn": [5000, 5000, 0]}]}}
        for k, v in ((extra or {}).get(i) or {}).items():
            if isinstance(v, dict) and k in r:
                for kk, vv in v.items():
                    if isinstance(vv, dict) and isinstance(r[k].get(kk), dict):
                        r[k][kk].update(vv)
                    else:
                        r[k][kk] = vv
            else:
                r[k] = v
        return r

    replies = []
    for i, (x, y, ga) in enumerate(path):
        if i + 1 < len(path):
            vx, vy = path[i + 1][0] - x, path[i + 1][1] - y
        else:
            vx = vy = 0.0
        # velocity recorded at tick i is the motion that produced position i (predictor uses vel[t])
        pvx, pvy = (x - path[i - 1][0], y - path[i - 1][1]) if i else (0.0, 0.0)
        replies.append(reply(i, x, y, ga, pvx, pvy))
    replies[0]["spatial"]["lines"] = lines
    return {"initial": replies[0], "steps": replies[1:]}


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.geo = gm.derive(raw_from_lines(sorted_spec(box(0, -1000, 300, 0))), "test")

    def kinds(self, trace, **kw):
        events, summary = detect.scan(trace, params=detect.Params(**kw))
        return sorted({e["kind"] for e in events}), events, summary

    def test_clean_trace_has_no_events(self):
        path = [(-1000 + 10 * i, 500.0, 1) for i in range(30)]
        k, ev, s = self.kinds(make_trace(self.geo, path))
        self.assertEqual(k, [])
        self.assertEqual(s["live_ticks"], 30)

    def test_wall_crossing_and_inside(self):
        # walk right through the block's left wall at y = -500
        path = [(-400 + 50 * i, -500.0, 1) for i in range(12)]
        k, ev, _ = self.kinds(make_trace(self.geo, path))
        self.assertIn("line_crossing", k)
        self.assertIn("inside_solid", k)
        crossing = [e for e in ev if e["kind"] == "line_crossing"]
        self.assertTrue(any(e["evidence"]["kind"] == "lwall" and e["evidence"]["point"] == "right" for e in crossing))

    def test_floor_crossing(self):
        path = [(150.0, 100.0, 1), (150.0, 40.0, 1), (150.0, -30.0, 1)]
        k, ev, _ = self.kinds(make_trace(self.geo, path))
        self.assertTrue(any(e["kind"] == "line_crossing" and e["evidence"]["kind"] == "floor" for e in ev))

    def test_landing_on_floor_is_not_a_crossing(self):
        path = [(150.0, 100.0, 1), (150.0, 40.0, 1), (150.0, 0.0, 0), (150.0, 0.0, 0)]
        k, _, _ = self.kinds(make_trace(self.geo, path))
        self.assertNotIn("line_crossing", k)

    def test_snap_and_edge_snap(self):
        path = [(100.0, 0.0, 0), (110.0, 0.0, 0), (120.0, 0.0, 0), (40.0, 0.0, 0)]
        tr = make_trace(self.geo, path)
        tr["steps"][2]["observation"]["air_velocity_x"] = 10.0  # the game says it moved +10, it moved -80
        for st in tr["steps"]:
            st["spatial"]["fighter"]["floor_line_id"] = 0
        tr["initial"]["spatial"]["fighter"]["floor_line_id"] = 0
        k, ev, _ = self.kinds(tr)
        snaps = [e for e in ev if e["kind"] == "position_snap"]
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["evidence"]["class"], "edge_snap")

    def test_unlinked_floor_switch(self):
        geo = gm.derive(raw_from_lines([(0, [(0, 0), (100, 0)], 0), (0, [(500, -50), (600, -50)], 0)]), "test")
        path = [(50.0, 0.0, 0), (550.0, -50.0, 0)]
        tr = make_trace(geo, path)
        tr["initial"]["spatial"]["fighter"]["floor_line_id"] = 0
        tr["steps"][0]["spatial"]["fighter"]["floor_line_id"] = 1
        k, _, _ = self.kinds(tr)
        self.assertIn("floor_switch_unlinked", k)

    def test_break_without_hitter_and_with_weapon(self):
        path = [(-3000.0, 500.0, 1)] * 3
        extra = {2: {"spatial": {"target_live_mask": 0}, "targets": {"remaining_mask": 0}}}
        tr = make_trace(self.geo, path, extra=extra)
        k, _, _ = self.kinds(tr)
        self.assertIn("break_without_plausible_hitter", k)
        weapon = {"serial": 7, "kind": 0, "translate": [4900.0, 5000.0], "velocity": [50.0, 0.0]}
        extra[1] = {"entity": {"weapons": [weapon]}}
        tr = make_trace(self.geo, path, extra=extra)
        k, _, _ = self.kinds(tr)
        self.assertNotIn("break_without_plausible_hitter", k)

    def test_break_through_solid(self):
        geo = gm.derive(raw_from_lines(sorted_spec(box(4500, 4000, 4700, 6000))), "test")
        path = [(4400.0, 4810.0, 1)] * 3
        extra = {2: {"spatial": {"target_live_mask": 0}, "targets": {"remaining_mask": 0}},
                 1: {"entity": {"fighter": {"attack_active": 1}}}, }
        tr = make_trace(geo, path, extra=extra)
        k, ev, _ = self.kinds(tr)
        self.assertIn("break_through_solid", k)

    def test_bounds_and_platform_tag(self):
        path = [(4900.0, 0.0, 1), (9700.0, 0.0, 1)]
        extra = {0: {"observation": {"fighter_status_id": 226}, "input": {"stick_x": 80}}}
        tr = make_trace(self.geo, path, extra=extra)
        k, ev, _ = self.kinds(tr)
        self.assertIn("beyond_map_bounds", k)
        self.assertIn("beyond_camera_bounds", k)
        self.assertIn("d1_transn_cosf", ev[0]["platform_sensitive"])

    def test_moving_group_frame(self):
        # a solid floor on a moving group: standing on it while it rises is not a crossing
        geo = gm.derive(raw_from_lines([(0, [(-100, 0), (100, 0)], 0)], groups=[2]), "test")
        path = [(0.0, 1000.0 + 10 * i, 0) for i in range(5)]
        groups = [[{"id": 2, "translated": 1, "translate": [0.0, 1000.0 + 10 * i]}] for i in range(5)]
        k, _, _ = self.kinds(make_trace(geo, path, groups=groups))
        self.assertNotIn("line_crossing", k)
        # the same positions with the platform rising faster: the feet end below the moving floor
        groups = [[{"id": 2, "translated": 1, "translate": [0.0, 1000.0 + 30 * i]}] for i in range(5)]
        k, _, _ = self.kinds(make_trace(geo, path, groups=groups))
        self.assertIn("line_crossing", k)

    def test_native_flag(self):
        tr = make_trace(self.geo, [(-1000.0, 500.0, 1)] * 2, extra={1: {"spatial": {"anomaly_flags": 4}}})
        k, _, _ = self.kinds(tr)
        self.assertIn("native_anomaly_flag", k)

    def test_event_schema_fields(self):
        path = [(-400 + 50 * i, -500.0, 1) for i in range(12)]
        events, _ = detect.scan(make_trace(self.geo, path), source={"trace": "x"})
        need = {"schema", "event_id", "kind", "mechanisms", "step", "step_from", "step_to", "input_tick", "score",
                "threshold", "source", "geometry_sha256", "ecb", "fighter", "evidence", "platform_sensitive", "detector",
                "needs_replay"}
        for e in events:
            self.assertEqual(need - set(e), set())
            self.assertEqual(e["schema"], detect.EVENT_SCHEMA)
            json.dumps(e)


if __name__ == "__main__":
    unittest.main(verbosity=2)
