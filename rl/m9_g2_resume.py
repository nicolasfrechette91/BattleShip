"""M9-g2: continuity of the line across sessions (decision 5; proposal 6.2; decision R14): the saved state, the pinned digests, the continuity assertions
and the refusals. Zero native ticks; nothing here learns.

Saved at the session close (`session/final_state.json`): the final checkpoint's model.zip (SB3's save: the policy and `policy.optimizer.pth`, the Adam
moments and step counts), its `curriculum_state.json`, the pinned tape baseline, each with its sha256, plus the line contract digest and the executable pin.
A later session copies the three files into its `input/` directory, checks every digest against the ones its approval names, loads the model with
`PPO.load(model.zip, env=<the training vector>)`, asserts `num_timesteps`, `_n_updates` and every parameter's Adam step count equal the saved values,
sets the training seed 1000 + k, and continues with `learn(reset_num_timesteps=False)`.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import m9_artifacts as A
import m9_g2_contract as G

RESUME_CONTRACT = "m9_g2_resume_v1"
MEMBERS = ("policy.pth", "policy.optimizer.pth")


class ResumeError(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_member_digests(model_zip: Path, members: Any = MEMBERS) -> Dict[str, str]:
    out: Dict[str, str] = {}
    with zipfile.ZipFile(model_zip) as z:
        names = set(z.namelist())
        for m in members:
            out[m] = hashlib.sha256(z.read(m)).hexdigest() if m in names else None       # type: ignore[assignment]
    return out


def saved_counters(model_zip: Path) -> Dict[str, Any]:
    """num_timesteps, _n_updates and the Adam step count of every parameter, read from the zip without building a model (torch loads tensors only).
    A zip without SB3's `data` member is the synthetic learner's stand-in format (tests only): its counters are read from its JSON members."""
    with zipfile.ZipFile(model_zip) as z:
        names = set(z.namelist())
        if "data" not in names and "stub_model.json" in names:
            st = json.loads(z.read("stub_model.json"))
            opt_j = json.loads(z.read("policy.optimizer.pth")) if "policy.optimizer.pth" in names else {}
            steps = {str(k): float(v) for k, v in sorted(dict(opt_j.get("adam_steps") or {}).items())}
            return {"num_timesteps": int(st.get("num_timesteps", 0)), "n_updates": int(st.get("n_updates", 0)), "seed": st.get("seed"), "adam_steps": steps, "adam_params": len(steps),
                    "format": "synthetic_stub"}
        import torch

        data = json.loads(z.read("data"))
        opt = torch.load(io.BytesIO(z.read("policy.optimizer.pth")), map_location="cpu", weights_only=True)
    steps = {str(k): float(v["step"]) for k, v in sorted(opt.get("state", {}).items()) if isinstance(v, dict) and "step" in v}
    return {"num_timesteps": int(data.get("num_timesteps", 0)), "n_updates": int(data.get("_n_updates", 0)), "seed": data.get("seed"), "adam_steps": steps,
            "adam_params": len(opt.get("param_groups", [{}])[0].get("params", [])) if opt.get("param_groups") else 0}


def live_counters(model: Any) -> Dict[str, Any]:
    opt = model.policy.optimizer.state_dict()
    steps = {str(k): float(v["step"]) for k, v in sorted(opt.get("state", {}).items()) if isinstance(v, dict) and "step" in v}
    return {"num_timesteps": int(model.num_timesteps), "n_updates": int(getattr(model, "_n_updates", 0)), "seed": getattr(model, "seed", None), "adam_steps": steps,
            "adam_params": len(opt.get("param_groups", [{}])[0].get("params", [])) if opt.get("param_groups") else 0}


def tensors_equal(a: Mapping[str, Any], b: Mapping[str, Any]) -> List[str]:
    """Names of tensors that differ bit for bit (or are missing) between two state dicts (nested dicts and lists are walked)."""
    import torch

    diffs: List[str] = []

    def walk(x: Any, y: Any, path: str) -> None:
        if isinstance(x, torch.Tensor) or isinstance(y, torch.Tensor):
            if not (isinstance(x, torch.Tensor) and isinstance(y, torch.Tensor)):
                diffs.append(path)
            elif x.shape != y.shape or x.dtype != y.dtype or not torch.equal(x, y):
                diffs.append(path)
            return
        if isinstance(x, Mapping) and isinstance(y, Mapping):
            for k in sorted(set(x) | set(y), key=str):
                if k not in x or k not in y:
                    diffs.append(f"{path}.{k}")
                else:
                    walk(x[k], y[k], f"{path}.{k}")
            return
        if isinstance(x, (list, tuple)) and isinstance(y, (list, tuple)):
            if len(x) != len(y):
                diffs.append(f"{path}[len]")
                return
            for i, (xi, yi) in enumerate(zip(x, y)):
                walk(xi, yi, f"{path}[{i}]")
            return
        if x != y:
            diffs.append(path)

    walk(a, b, "")
    return diffs


def model_state(model: Any) -> Dict[str, Any]:
    return {"policy": {k: v.detach().cpu().clone() for k, v in model.policy.state_dict().items()}, "optimizer": _clone(model.policy.optimizer.state_dict())}


def _clone(x: Any) -> Any:
    import torch

    if isinstance(x, torch.Tensor):
        return x.detach().cpu().clone()
    if isinstance(x, Mapping):
        return {k: _clone(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clone(v) for v in x]
    return x


# -- the final-state record ------------------------------------------------------------------------------------------------------------


def final_state_record(*, final_dir: Path, tape_baseline_path: Path, session: int, line_contract_sha256: str, executable_sha256: Optional[str], extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The pinned state a later session resumes from: model.zip (and its members), curriculum_state.json, the pinned tape baseline."""
    final_dir, tape_baseline_path = Path(final_dir), Path(tape_baseline_path)
    mz = final_dir / "model.zip"
    rec = {"resume": RESUME_CONTRACT, "session": int(session), "line_contract_sha256": line_contract_sha256, "executable_sha256": executable_sha256,
           "model_zip": {"path": str(mz), "sha256": sha256_file(mz), "bytes": mz.stat().st_size, "members": zip_member_digests(mz)},
           "curriculum_state": {"path": str(final_dir / "curriculum_state.json"), "sha256": sha256_file(final_dir / "curriculum_state.json")},
           "tape_baseline": {"path": str(tape_baseline_path), "sha256": sha256_file(tape_baseline_path)} if tape_baseline_path.is_file() else None,
           "counters": saved_counters(mz), "next_session_seed": G.SESSION_SEED_BASE + int(session) + 1}
    if extra:
        rec.update(extra)
    return rec


def copy_inputs(final_state: Mapping[str, Any], dest: Path, *, expect: Mapping[str, str]) -> Dict[str, Any]:
    """Copy the previous session's three files into <dest> and check each copy's sha256 against `expect` ({model_zip, curriculum_state, tape_baseline})
    and against the final-state record. Refuses any difference before anything is loaded."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    out: Dict[str, Any] = {"files": {}, "problems": []}
    for key, name in (("model_zip", "model.zip"), ("curriculum_state", "curriculum_state.json"), ("tape_baseline", "tape_baseline.json")):
        src_rec = final_state.get(key)
        if not src_rec:
            out["problems"].append(f"{key}: not in the final-state record")
            continue
        src = Path(src_rec["path"])
        got_src = sha256_file(src)
        shutil.copyfile(src, dest / name)
        got = sha256_file(dest / name)
        out["files"][key] = {"source": str(src), "copy": str(dest / name), "sha256": got}
        if not (got == got_src == src_rec["sha256"] == expect.get(key)):
            out["problems"].append(f"{key}: sha256 {got[:16]} (source {got_src[:16]}, record {str(src_rec['sha256'])[:16]}, approval {str(expect.get(key))[:16]})")
    out["ok"] = not out["problems"]
    if not out["ok"]:
        raise ResumeError("; ".join(out["problems"]))
    return out


def check_resume_compat(curriculum_state: Mapping[str, Any], *, line_contract_sha256: str, executable_sha256: Optional[str], saved_executable: Optional[str], ppo: Mapping[str, Any]) -> List[str]:
    """Refusals of a resume: a changed line contract digest, a changed executable, a changed PPO value (M7b's rule, applied to the line)."""
    problems: List[str] = []
    if curriculum_state.get("line_contract_sha256") != line_contract_sha256:
        problems.append("the line contract digest differs from the saved one")
    if saved_executable is not None and executable_sha256 != saved_executable:
        problems.append("the executable differs from the one the saved state was produced with")
    if curriculum_state.get("stalled"):
        problems.append("the saved state is STALLED: the line ended")
    saved_ppo = dict(curriculum_state.get("ppo") or {})
    for k, v in dict(ppo).items():
        if saved_ppo.get(k) != v:
            problems.append(f"PPO value {k} differs from the saved {saved_ppo.get(k)!r}")
    return problems


def assert_continuity(model: Any, saved: Mapping[str, Any]) -> Dict[str, Any]:
    """After PPO.load: num_timesteps, _n_updates and every Adam step count equal the saved values; raises ResumeError otherwise."""
    live = live_counters(model)
    problems: List[str] = []
    for k in ("num_timesteps", "n_updates", "adam_params"):
        if live[k] != saved[k]:
            problems.append(f"{k}: live {live[k]} saved {saved[k]}")
    if live["adam_steps"] != saved["adam_steps"]:
        problems.append("Adam step counts differ")
    if problems:
        raise ResumeError("continuity: " + "; ".join(problems))
    return {"ok": True, "live": live}


def write_final_state(path: Path, rec: Mapping[str, Any]) -> str:
    A.write_json(path, A.stamp(dict(rec)), overwrite=False)
    return sha256_file(path)


def contract_description() -> Dict[str, Any]:
    return {"contract": RESUME_CONTRACT, "saved": ["model.zip (policy + policy.optimizer.pth)", "curriculum_state.json", "tape_baseline.json"], "load": "PPO.load(model.zip, env=vec)",
            "asserts": ["num_timesteps", "_n_updates", "every Adam step count"], "seed": f"{G.SESSION_SEED_BASE} + k", "learn": "reset_num_timesteps=False",
            "refuses": ["line contract digest", "executable", "PPO value", "input digest", "STALLED"]}
