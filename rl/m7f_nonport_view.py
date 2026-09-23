"""M7f: prove that PORT-only decomp edits leave the non-PORT (byte-matching) source unchanged.

The decomp checkout embedded in this repository is source-only (no Makefile, no asm/, no IDO toolchain), so the
N64 matching build cannot run here. The applicable local check is therefore at the preprocessor level: resolve every
conditional that tests the PORT macro exactly as a compiler with PORT *undefined* would, keep every other line
verbatim (including other conditionals and their directives), and compare the resulting non-PORT view of each file at
a git revision against the working tree. If the two views are byte-identical, the non-PORT translation unit the
matching build compiles is unchanged, whatever was added inside PORT-only blocks.

Recognised forms (all others containing the token PORT are reported as unsupported, never silently accepted):
    #ifdef PORT / #ifndef PORT / #if defined(PORT) / #if !defined(PORT) / #if defined PORT
    with #else / #elif / #endif at any nesting depth. An #elif inside a PORT conditional is rejected.

Usage:
    python rl/m7f_nonport_view.py --rev HEAD decomp/src/it/itground/ittarget.c ...
    python rl/m7f_nonport_view.py --self-test
Exit codes: 0 identical, 1 difference or unsupported construct, 2 usage / git error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

_DIRECTIVE = re.compile(r"^\s*#\s*(\w+)\b(.*)$")
_PORT_TOKEN = re.compile(r"\bPORT\b")
_PORT_FORMS = {
    "ifdef": {"PORT": True},
    "ifndef": {"PORT": False},
}
_IF_DEFINED = re.compile(r"^\s*(!?)\s*defined\s*(?:\(\s*PORT\s*\)|\s+PORT)\s*$")


class UnsupportedConstruct(Exception):
    pass


def _port_condition(kind: str, rest: str) -> Optional[bool]:
    """True/False = the conditional tests 'PORT is defined' / 'PORT is not defined'; None = not a PORT test."""
    rest_code = rest.split("//", 1)[0].split("/*", 1)[0].strip()
    if kind in _PORT_FORMS:
        return _PORT_FORMS[kind].get(rest_code) if rest_code == "PORT" else None
    if kind == "if":
        m = _IF_DEFINED.match(rest_code)
        if m:
            return m.group(1) != "!"
        if _PORT_TOKEN.search(rest_code):
            raise UnsupportedConstruct(f"#if expression mixes PORT with other terms: {rest_code!r}")
    return None


def nonport_view(text: str) -> str:
    """Return the text a compiler without PORT would see, for PORT conditionals only. Line endings are preserved."""
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    # stack entries: ("port", keep_current_branch, seen_else) or ("other", None, None)
    stack: List[Tuple[str, Optional[bool], Optional[bool]]] = []

    def emitting() -> bool:
        return all(kind != "port" or keep for kind, keep, _ in stack)

    for n, line in enumerate(lines, 1):
        m = _DIRECTIVE.match(line)
        if m:
            kind, rest = m.group(1), m.group(2)
            if kind in ("if", "ifdef", "ifndef"):
                cond = _port_condition(kind, rest)
                if cond is not None:
                    # PORT undefined: the branch testing 'defined' is dropped, 'not defined' is kept.
                    stack.append(("port", not cond, False))
                    continue
                stack.append(("other", None, None))
                if emitting():
                    out.append(line)
                continue
            if kind in ("else", "elif", "endif"):
                if not stack:
                    raise UnsupportedConstruct(f"line {n}: #{kind} without an open conditional")
                top_kind, keep, seen_else = stack[-1]
                if top_kind == "port":
                    if kind == "elif":
                        raise UnsupportedConstruct(f"line {n}: #elif inside a PORT conditional")
                    if kind == "else":
                        if seen_else:
                            raise UnsupportedConstruct(f"line {n}: second #else in a PORT conditional")
                        stack[-1] = ("port", not keep, True)
                        continue
                    stack.pop()
                    continue
                if kind == "endif":
                    stack.pop()
                if emitting():
                    out.append(line)
                continue
        if emitting():
            out.append(line)
    if stack:
        raise UnsupportedConstruct(f"{len(stack)} conditional(s) left open at end of file")
    return "".join(out)


def _git_show(rev: str, rel: str) -> str:
    # Paths inside the decomp submodule are resolved against the submodule's own HEAD.
    rel_posix = rel.replace("\\", "/")
    if rel_posix.startswith("decomp/"):
        cwd, path = REPO_ROOT / "decomp", rel_posix[len("decomp/"):]
    else:
        cwd, path = REPO_ROOT, rel_posix
    res = subprocess.run(["git", "-c", "core.autocrlf=false", "show", f"{rev}:{path}"], cwd=cwd,
                         capture_output=True)
    if res.returncode != 0:
        raise FileNotFoundError(res.stderr.decode("utf-8", "replace").strip())
    return res.stdout.decode("utf-8")


def _normalise_eol(text: str) -> str:
    return text.replace("\r\n", "\n")


def code_tokens(text: str) -> str:
    """Comments removed and whitespace runs collapsed, string/char literals kept intact: the code the compiler sees."""
    out: List[str] = []
    i, n = 0, len(text)
    pending_space = False
    while i < n:
        c = text[i]
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            pending_space = True
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            pending_space = True
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            if pending_space and out:
                out.append(" ")
            pending_space = False
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if c.isspace():
            # a newline ends a preprocessor directive, so keep newlines distinct from other whitespace
            pending_space = True if not out or out[-1] != "\n" else pending_space
            if c == "\n":
                if out and out[-1] != "\n":
                    out.append("\n")
                pending_space = False
            i += 1
            continue
        if pending_space and out and out[-1] != "\n":
            out.append(" ")
        pending_space = False
        out.append(c)
        i += 1
    return "".join(out)


def compare(rel: str, rev: str) -> dict:
    work = (REPO_ROOT / rel).read_bytes().decode("utf-8")
    old = _git_show(rev, rel)
    # git stores LF; the working tree is CRLF under core.autocrlf=true. Compare EOL-normalised text.
    v_old = _normalise_eol(nonport_view(old))
    v_new = _normalise_eol(nonport_view(work))
    return {
        "file": rel.replace("\\", "/"),
        "rev": rev,
        "full_text_changed": _normalise_eol(old) != _normalise_eol(work),
        "nonport_identical": v_old == v_new,
        "nonport_code_tokens_identical": code_tokens(v_old) == code_tokens(v_new),
        "nonport_sha256_rev": hashlib.sha256(v_old.encode("utf-8")).hexdigest(),
        "nonport_sha256_worktree": hashlib.sha256(v_new.encode("utf-8")).hexdigest(),
        "nonport_lines": v_new.count("\n"),
    }


VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat")
# N64-style non-PORT environment for the MSVC preprocessor (PORT deliberately NOT defined).
CL_DEFINES = ("_LANGUAGE_C", "F3DEX_GBI_2", "_MIPS_SZLONG=32", "_MIPS_SZINT=32", "__sgi", "NDEBUG", "REGION_US",
              "VERSION_US")


def _normalise_pp(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(ln for ln in lines if ln) + "\n"


def cl_compare(rels: Sequence[str], rev: str, scratch: Path) -> List[dict]:
    """Canonical check with the real preprocessor: `cl /EP` (PORT undefined) of the file at `rev` and of the working
    tree, both resolved against the working-tree headers with the file's own directory first on the include path.
    The normalised outputs (LF, trailing blanks and empty lines dropped) must be identical; a non-zero cl exit or a
    missing output fails the check instead of comparing a truncated translation unit."""
    if not VCVARS.is_file():
        raise FileNotFoundError(f"MSVC vcvars64.bat not found: {VCVARS}")
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    jobs = []
    for rel in rels:
        rel = rel.replace("\\", "/")
        src = REPO_ROOT / rel
        old = scratch / f"rev_{Path(rel).name}"
        old.write_bytes(_git_show(rev, rel).encode("utf-8"))
        for tag, path in (("rev", old), ("work", src)):
            jobs.append((rel, tag, path, scratch / f"{tag}_{Path(rel).stem}.i", scratch / f"{tag}_{Path(rel).stem}.err"))
    incs = [REPO_ROOT / "include", REPO_ROOT / "decomp" / "include", REPO_ROOT / "decomp" / "src"]
    lines = ["@echo off", f'call "{VCVARS}" >nul']
    for rel, tag, path, out, err in jobs:
        src_dir = (REPO_ROOT / rel).parent
        args = " ".join([f'/I"{src_dir}"'] + [f'/I"{i}"' for i in incs] + [f"/D{d}" for d in CL_DEFINES])
        lines.append(f'cl /nologo /EP /TC {args} "{path}" > "{out}" 2> "{err}"')
        # redirection first: "echo x 0>> f" would parse the digit as a stream-handle redirect
        lines.append(f'>> "{scratch / "exit_codes.txt"}" echo {tag} {Path(rel).name} %ERRORLEVEL%')
    bat = scratch / "run_cl.bat"
    (scratch / "exit_codes.txt").unlink(missing_ok=True)
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    subprocess.run(["cmd", "/c", str(bat)], check=False)
    codes = {}
    for ln in (scratch / "exit_codes.txt").read_text(encoding="utf-8").splitlines():
        tag, name, code = ln.split()
        codes[(tag, name)] = int(code)
    results = []
    for rel in rels:
        rel = rel.replace("\\", "/")
        name, stem = Path(rel).name, Path(rel).stem
        texts = {}
        for tag in ("rev", "work"):
            p = scratch / f"{tag}_{stem}.i"
            texts[tag] = _normalise_pp(p.read_text(encoding="utf-8", errors="replace")) if p.is_file() else ""
        ok_exit = codes.get(("rev", name)) == 0 and codes.get(("work", name)) == 0
        results.append({"file": rel, "rev": rev, "cl_exit_ok": ok_exit,
                        "preprocessed_lines": texts["work"].count("\n"),
                        "sha256_rev": hashlib.sha256(texts["rev"].encode("utf-8")).hexdigest(),
                        "sha256_work": hashlib.sha256(texts["work"].encode("utf-8")).hexdigest(),
                        "identical": ok_exit and bool(texts["work"]) and texts["rev"] == texts["work"]})
    return results


def self_test() -> int:
    cases = [
        ("a\n#ifdef PORT\nb\n#endif\nc\n", "a\nc\n"),
        ("a\n#ifdef PORT\nb\n#else\nx\n#endif\nc\n", "a\nx\nc\n"),
        ("#ifndef PORT\nk\n#else\nd\n#endif\n", "k\n"),
        ("#if defined(PORT)\nd\n#endif\n#if !defined(PORT)\nk\n#endif\n", "k\n"),
        ("#if X\n#ifdef PORT\nd\n#else\nk\n#endif\n#endif\n", "#if X\nk\n#endif\n"),
        ("#ifdef PORT\n#if X\nd\n#endif\n#endif\ne\n", "e\n"),
        ("  #ifdef PORT\n    x;\n  #endif\ny\n", "y\n"),
        ("#ifdef PORT /* c */\nd\n#endif // PORT\n", ""),
        ("a\r\n#ifdef PORT\r\nb\r\n#endif\r\n", "a\r\n"),
    ]
    bad = 0
    for i, (src, want) in enumerate(cases):
        got = nonport_view(src)
        if got != want:
            bad += 1
            print(f"self-test {i} FAIL: {got!r} != {want!r}")
    for i, src in enumerate(["#if defined(PORT) && X\n#endif\n", "#ifdef PORT\n#elif Y\n#endif\n", "#ifdef PORT\n"]):
        try:
            nonport_view(src)
        except UnsupportedConstruct:
            continue
        bad += 1
        print(f"self-test reject {i} FAIL: accepted {src!r}")
    token_cases = [
        ("int a; /* c */\nint  b;\n", "int a;\n// x\nint b;\n", True),
        ('char *s = "/* no */";\n', 'char *s = "/* no  */";\n', False),
        ("a = 1;\n", "a = 2;\n", False),
        ("#define X 1\n", "#define X 1 // y\n", True),
    ]
    for i, (a, b, same) in enumerate(token_cases):
        if (code_tokens(a) == code_tokens(b)) != same:
            bad += 1
            print(f"self-test tokens {i} FAIL: {code_tokens(a)!r} vs {code_tokens(b)!r}")
    total = len(cases) + 3 + len(token_cases)
    print(f"self-test: {'PASS' if not bad else 'FAIL'} ({total} cases, {bad} failed)")
    return 0 if not bad else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="repo-relative paths (decomp/... paths use the submodule's history)")
    ap.add_argument("--rev", default="HEAD", help="git revision to compare against (default HEAD)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", type=Path, help="write the comparison result to this file")
    ap.add_argument("--cl", type=Path, metavar="SCRATCH_DIR",
                    help="also run the canonical MSVC cl /EP comparison, writing its intermediates to SCRATCH_DIR")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.files:
        ap.error("no files given")
    if args.cl is not None:
        cl = cl_compare(args.files, args.rev, args.cl)
        for r in cl:
            print(json.dumps(r))
        print("CL /EP NON-PORT TRANSLATION UNITS: " + ("IDENTICAL" if all(r["identical"] for r in cl) else "DIFFERENT"))
        if args.json:
            args.json.write_text(json.dumps({"schema": "battleship_m7f_nonport_cl_v1", "defines": list(CL_DEFINES),
                                             "results": cl}, indent=1) + "\n", encoding="utf-8")
        if not all(r["identical"] for r in cl):
            return 1
    results, status = [], 0
    for rel in args.files:
        try:
            r = compare(rel, args.rev)
        except UnsupportedConstruct as exc:
            r, status = {"file": rel, "error": f"unsupported: {exc}"}, 1
        except (FileNotFoundError, OSError) as exc:
            print(f"{rel}: {exc}", file=sys.stderr)
            return 2
        else:
            if not r["nonport_identical"]:
                status = 1
        results.append(r)
        print(json.dumps(r))
    if args.json:
        args.json.write_text(json.dumps({"schema": "battleship_m7f_nonport_view_v1", "results": results}, indent=1)
                             + "\n", encoding="utf-8")
    print("NONPORT VIEW: " + ("IDENTICAL" if status == 0 else "DIFFERENT OR UNSUPPORTED"))
    return status


if __name__ == "__main__":
    sys.exit(main())
