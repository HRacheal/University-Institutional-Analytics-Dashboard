"""Import Colab-trained Drive backup sets into the local working copy and register them in the artifact manifest.

Used on 2026-11-11 to replace the 8 Batch 1 tasks that had originally been trained on the local Windows machine with
their Google Colab retrains (MyDrive/analytics_project_outputs/<task>/). Inference-only: nothing is trained here.

    python -m pipelines.model_registry.import_colab_sets --source <folder holding the Drive sets> --task T [--task T ...] [--dry-run]

For each task set:
  1. every file is checked against the set's backup_manifest.json (SHA-256); any mismatch aborts before anything changes;
  2. local task files that will be replaced or no longer exist in the set are MOVED to _superseded_local/<stamp>/ (never deleted);
  3. files are copied (shared files run_summary.json / experiment_log.jsonl and training logs are not imported) and re-verified;
  4. the manifest entries of these tasks only are rebuilt (manifest.build) and merged; all other tasks are left as they were.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import DW_ROOT, MANIFEST_PATH
from .manifest import SHARED, _files_of, build, sha256

SKIP_PREFIX = ("experiments/logs/",)


def import_sets(source: Path, tasks: list[str], dw: Path = DW_ROOT, dry_run: bool = False) -> dict:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    report = {"source": str(source), "stamp": stamp, "tasks": {}}
    sets = {}
    for t in tasks:                                            # 1. verify every set first
        bm = json.loads((source / t / "backup_manifest.json").read_text())
        bad = [rel for rel, e in bm.items() if sha256(source / t / rel) != e["sha256"]]
        if bad:
            raise SystemExit(f"{t}: {len(bad)} file(s) do not match the set's backup_manifest.json: {bad[:3]}")
        sets[t] = bm
    for t, bm in sets.items():
        imp = [rel for rel in bm if rel not in SHARED and not rel.startswith(SKIP_PREFIX)]
        old = set(_files_of(t, dw)) | {str(p.relative_to(dw)).replace("\\", "/") for p in (dw / "experiments/checkpoints" / t).glob("*") if p.is_file()}
        archived, copied, unchanged = [], [], []
        for rel in sorted(old | set(imp)):
            d = dw / rel
            new = bm.get(rel) if rel in imp else None
            if d.exists() and (new is None or sha256(d) != new["sha256"]):
                arch = dw / "_superseded_local" / stamp / rel
                if not dry_run:
                    arch.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(d), str(arch))
                archived.append(rel)
            if new is None:
                continue
            if d.exists() and sha256(d) == new["sha256"]:
                unchanged.append(rel)
                continue
            if not dry_run:
                d.parent.mkdir(parents=True, exist_ok=True)
                part = d.with_name(d.name + ".part")
                shutil.copyfile(source / t / rel, part)
                if sha256(part) != new["sha256"]:
                    part.unlink()
                    raise SystemExit(f"copy verification failed: {rel}")
                part.replace(d)
            copied.append(rel)
        report["tasks"][t] = {"imported": len(copied), "unchanged": len(unchanged), "archived": len(archived), "archived_files": archived}
    if dry_run:
        return report
    # 4. rebuild the manifest entries of these tasks only (drive locations from the imported sets)
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fresh = build(dw, drive_root=source)
    for t in tasks:
        man["tasks"][t] = {**fresh["tasks"][t], "trained_in": "GOOGLE_COLAB", "retrained_in_colab_utc": report["stamp"]}
        for rel in [r for r, e in man["files"].items() if e["task"] == t]:
            del man["files"][rel]
        for rel, e in fresh["files"].items():
            if e["task"] == t:
                man["files"][rel] = e
        man["drive_backup_sets"][t] = len(sets[t])
    man["files"] = dict(sorted(man["files"].items()))
    man["drive_backup_sets"] = dict(sorted(man["drive_backup_sets"].items()))
    man.setdefault("history", []).append({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                          "event": "Batch 1 tasks replaced by their Google Colab retrains (previous local-trained files archived "
                                                   f"in _superseded_local/{stamp}/)", "tasks": tasks})
    MANIFEST_PATH.write_text(json.dumps(man, indent=1), encoding="utf-8")
    report["manifest"] = str(MANIFEST_PATH)
    return report


PORTABLE_SET_B1 = "_batch1_colab_retrain_portable"


def import_portable(source: Path, dw: Path = DW_ROOT) -> list[str]:
    """Import a portable XGBoost export set (<source>/backup_manifest.json + portable_xgboost/<task>/xgboost.{booster.json,
    portable.joblib}) made in Colab from a Colab-trained artifact, verify SHA-256 and register it in the manifest."""
    bm = json.loads((source / "backup_manifest.json").read_text())
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    done = []
    for rel, e in bm.items():
        if rel.startswith("_"):
            continue
        src = source / rel
        if sha256(src) != e["sha256"]:
            raise SystemExit(f"{rel}: SHA-256 does not match the portable set's backup_manifest.json")
        task, name = rel.split("/")[1], rel.split("/")[2]
        zone = "uci" if task.startswith("uci_") else "synthetic"
        local_rel = f"models/{zone}/{task}/{name}"
        d = dw / local_rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d)
        if sha256(d) != e["sha256"]:
            raise SystemExit(f"copy verification failed: {local_rel}")
        man["files"][local_rel] = {"role": "model_portable_export", "task": task, "required_for_dashboard": True, "sha256": e["sha256"],
                                   "bytes": e["bytes"], "drive_backup_set": PORTABLE_SET_B1, "drive_path": f"{PORTABLE_SET_B1}/{rel}",
                                   "persistent_location": f"MyDrive/analytics_project_outputs/{PORTABLE_SET_B1}/{rel}",
                                   "working_copy_matches_backup": True, "derived_from": f"models/{zone}/{task}/xgboost.joblib",
                                   "reason": "the original pickle's internal XGBoost serialisation does not load on the Windows XGBoost build"}
        m = man["tasks"][task]["models"]["xgboost"]
        m.setdefault("portable_export", {})["booster_json" if name.endswith(".json") else "sklearn_wrapper"] = local_rel
        done.append(local_rel)
    man["drive_backup_sets"][PORTABLE_SET_B1] = len([k for k in bm if not k.startswith("_")])
    man["files"] = dict(sorted(man["files"].items()))
    MANIFEST_PATH.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--task", action="append")
    ap.add_argument("--portable", action="store_true", help="--source is a portable XGBoost export set")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.portable:
        print("\n".join(import_portable(a.source)))
        return
    rep = import_sets(a.source, a.task, dry_run=a.dry_run)
    for t, r in rep["tasks"].items():
        print(f"{t:32s} imported {r['imported']:3d}  unchanged {r['unchanged']:3d}  archived {r['archived']:3d}")
    if a.log:
        a.log.write_text(json.dumps(rep, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
