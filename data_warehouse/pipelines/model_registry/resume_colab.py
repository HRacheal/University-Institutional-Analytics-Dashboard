"""Resume the completed project in a FRESH Colab runtime from Google Drive, without retraining anything.

Usage (in the single project notebook, after `from google.colab import drive; drive.mount('/content/drive')`):

    !python /content/drive/MyDrive/analytics_project_outputs/_final_restoration_and_dashboard/resume_colab.py --smoke

What it does (read-only on Drive: backups and the original ZIPs are never modified):
  1. If the project is not in /content/analytics_project yet, extracts MyDrive/University-Institutional-Analytics-Dashboard_latest.zip
     there (the ZIP is only read).
  2. Overlays the final code snapshot (_final_restoration_and_dashboard/code/) so the restore/registry tools and the
     skip-completed-tasks guard of run_all.py are present.
  3. Restores every artifact listed in the final artifact_manifest.json from the Drive backup sets into the project
     (copy -> SHA-256 check -> rename; differing local files are archived to data_warehouse/_superseded_local/, never deleted).
  4. Installs the verified complete run_summary.json (all 20 tasks completed), so run_all.py skips every finished task.
  5. Verifies all files against the manifest and, with --smoke, loads every selected model and predicts on a few real rows.
Exit code 0 only if everything verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DRIVE = Path("/content/drive/MyDrive")
ROOT = DRIVE / "analytics_project_outputs"
FINAL = ROOT / "_final_restoration_and_dashboard"
ZIP = DRIVE / "University-Institutional-Analytics-Dashboard_latest.zip"
WORK = Path("/content/analytics_project")
EXPECTED_COMPLETED = 20


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fail(msg: str):
    print(f"RESUME FAILED: {msg}", flush=True)
    sys.exit(1)


def find_dw() -> Path | None:
    for p in [WORK / "University-Institutional-Analytics-Dashboard" / "data_warehouse", *WORK.glob("*/data_warehouse"), WORK / "data_warehouse"]:
        if (p / "pipelines").is_dir():
            return p
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="load every selected model and predict on a few rows")
    ap.add_argument("--include-optional", action="store_true", help="also restore CV checkpoints, logs and prediction files")
    a = ap.parse_args(argv)
    if not ROOT.is_dir():
        fail(f"{ROOT} not found: mount Drive first (from google.colab import drive; drive.mount('/content/drive'))")
    for f in ("artifact_manifest.json", "run_summary.json", "code"):
        if not (FINAL / f).exists():
            fail(f"missing {FINAL / f}")

    # 1. project working copy
    dw = find_dw()
    if dw is None:
        if not ZIP.exists():
            fail(f"project not in {WORK} and {ZIP} not found")
        print(f"extracting {ZIP.name} -> {WORK} (ZIP is only read)", flush=True)
        WORK.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ZIP) as z:
            z.extractall(WORK)
        dw = find_dw()
        if dw is None:
            fail("data_warehouse/ not found after extraction")
    print(f"project: {dw}", flush=True)

    # 2. code snapshot overlay (code only; never artifacts)
    code = FINAL / "code"
    n = 0
    for src in code.rglob("*"):
        if src.is_file() and "__pycache__" not in src.parts:
            dst = dw.parent / src.relative_to(code)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            n += 1
    print(f"code snapshot: {n} files", flush=True)

    # 3. restore artifacts from the Drive backup sets
    man = dw / "artifacts" / "artifact_manifest.json"
    man.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FINAL / "artifact_manifest.json", man)
    cmd = [sys.executable, "-m", "pipelines.model_registry.restore", "--source", str(ROOT), "--layout", "drive", "--manifest", str(man),
           "--dest", str(dw), "--archive-conflicts", "--log", str(dw / "artifacts" / "restore_log.json")]
    if a.include_optional:
        cmd.append("--include-optional")
    r = subprocess.run(cmd, cwd=dw)
    if r.returncode != 0:
        fail("artifact restore reported problems (see data_warehouse/artifacts/restore_log.json)")

    # 4. completed-task status (prevents retraining)
    rs = dw / "reports" / "model_evaluation" / "run_summary.json"
    final_rs = FINAL / "run_summary.json"
    if rs.exists() and sha(rs) != sha(final_rs):
        arch = dw / "_superseded_local" / "run_summary_before_resume.json"
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rs, arch)
    rs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final_rs, rs)
    sys.path.insert(0, str(dw))
    from pipelines.model_training.run_all import completed_tasks
    done = completed_tasks(rs)
    print(f"completed tasks recorded: {len(done)}", flush=True)
    if len(done) < EXPECTED_COMPLETED:
        fail(f"only {len(done)} completed tasks in run_summary.json (expected {EXPECTED_COMPLETED})")

    # 5. verification
    r = subprocess.run([sys.executable, "-m", "pipelines.model_registry.restore", "--verify-only", "--manifest", str(man), "--dest", str(dw)], cwd=dw)
    if r.returncode != 0:
        fail("verification against the manifest failed")
    if a.smoke:
        smoke(dw, man)
    print("RESUME OK: all completed tasks restored; run_all.py will skip them (use --retrain TASK only to deliberately overwrite).", flush=True)


def smoke(dw: Path, man: Path):
    import warnings

    from pipelines.feature_engineering.common import load_dataset
    from pipelines.model_registry.loader import ModelRegistry
    warnings.filterwarnings("ignore")
    reg = ModelRegistry(dw, man)
    ok = bad = 0
    for task, e in reg.tasks.items():
        try:
            if e["kind"] == "forecasting":
                assert (dw / "reports/forecasting/forecasts_selected_method.csv").exists()
                print(f"  {task:46s} forecast outputs present (no model objects by design)")
                ok += 1
                continue
            lm = reg.get(task)
            if e["kind"] == "segmentation":
                import pandas as pd
                panel = next((q for q in (dw / "data/processed/modeling/synthetic/syn_student_term_panel.csv",
                                          dw.parent / "data/processed/modeling/synthetic/syn_student_term_panel.csv") if q.exists()), None)
                if panel is None:
                    raise FileNotFoundError("syn_student_term_panel.csv not found for the segmentation smoke test")
                out = lm.predict(pd.read_csv(panel, nrows=200).dropna(subset=e["features"]).head(5))
            else:
                df, _ = load_dataset(e["dataset"], e.get("zone", "SYNTHETIC"))
                out = lm.predict(df.head(5))
            print(f"  {task:46s} {lm.name}: loaded, predicted {out['n']} rows", flush=True)
            ok += 1
        except Exception as ex:
            bad += 1
            print(f"  {task:46s} FAILED: {ex!r}")
    print(f"smoke test: {ok} ok, {bad} failed", flush=True)
    if bad:
        fail("smoke test failures")


if __name__ == "__main__":
    main()
