"""Restore the artifacts listed in ``artifacts/artifact_manifest.json`` from a backup source into a project working copy.

    python -m pipelines.model_registry.restore --source "G:/My Drive/analytics_project_outputs" [--dest .] [--dry-run]
    python -m pipelines.model_registry.restore --source /content/drive/MyDrive/analytics_project_outputs --verify-only

--source is either the Drive output root (one folder per backup set, e.g. Google Drive for Desktop or a downloaded copy of
MyDrive/analytics_project_outputs) or another project tree with the same relative layout (``--layout tree``).

Safety rules
* the source is only read, never modified;
* every copied file is SHA-256 verified against the manifest (copied to ``*.part`` first, renamed only when it matches);
* a destination file that already matches is left untouched;
* a destination file that DIFFERS is never overwritten silently: it is reported as a conflict, or with
  ``--archive-conflicts`` it is first moved to ``_superseded_local/<timestamp>/<path>`` and then replaced.
Exit code 0 when every required artifact is present and verified, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import DW_ROOT, MANIFEST_PATH
from .manifest import sha256


class RestoreError(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not Path(path).exists():
        raise RestoreError(f"artifact manifest not found: {path}")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def detect_layout(source: Path) -> str:
    if any((d / "backup_manifest.json").exists() for d in source.iterdir() if d.is_dir()):
        return "drive"
    if (source / "models").exists() or (source / "reports").exists():
        return "tree"
    raise RestoreError(f"{source} is neither a Drive output root (folders with backup_manifest.json) nor a project tree")


def source_path(source: Path, layout: str, rel: str, entry: dict) -> Path | None:
    if layout == "tree":
        return source / rel
    return source / entry["drive_path"] if entry.get("drive_path") else None


def plan(manifest: dict, dest: Path, source: Path | None, layout: str | None, tasks=None, include_optional=False) -> list[dict]:
    out = []
    for rel, e in manifest["files"].items():
        if not include_optional and not e["required_for_dashboard"]:
            continue
        if tasks and e["task"] not in tasks and e["task"] != "shared":
            continue
        d = dest / rel
        item = {"path": rel, "task": e["task"], "role": e["role"], "expected_sha256": e["sha256"]}
        if d.exists():
            item["dest_sha256"] = sha256(d)
            if item["dest_sha256"] == e["sha256"]:
                out.append({**item, "action": "present_verified"})
                continue
            item["action"] = "conflict"
        else:
            item["action"] = "copy"
        src = source_path(source, layout, rel, e) if source else None
        if src is None or not src.exists():
            item["action"] = "conflict_no_source" if item["action"] == "conflict" else "missing_no_source"
            item["note"] = e["persistent_location"]
        else:
            item["source"] = str(src)
        out.append(item)
    return out


def execute(items: list[dict], dest: Path, archive_conflicts: bool, dry_run: bool) -> list[dict]:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    for it in items:
        if it["action"] not in ("copy", "conflict") or dry_run:
            continue
        if it["action"] == "conflict" and not archive_conflicts:
            it["result"] = "skipped: local file differs (rerun with --archive-conflicts to archive it and restore the backup)"
            continue
        src, d = Path(it["source"]), dest / it["path"]
        if sha256(src) != it["expected_sha256"]:
            it["result"] = "ERROR: backup file does not match the manifest SHA-256 (corrupt or changed backup); nothing copied"
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        if it["action"] == "conflict":
            arch = dest / "_superseded_local" / stamp / it["path"]
            arch.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(arch))
            it["archived_to"] = str(arch.relative_to(dest))
        part = d.with_name(d.name + ".part")
        shutil.copyfile(src, part)
        if sha256(part) != it["expected_sha256"]:
            part.unlink()
            it["result"] = "ERROR: copy verification failed"
            continue
        os.replace(part, d)
        it["result"] = "restored_verified"
    return items


def summarise(items):
    ok = {"present_verified", "restored_verified"}
    bad = [i for i in items if i["action"] != "present_verified" and i.get("result") not in ok]
    return {"files": len(items), "present_verified": sum(i["action"] == "present_verified" for i in items),
            "restored_verified": sum(i.get("result") == "restored_verified" for i in items), "problems": len(bad)}, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="backup source (Drive output root or project tree)")
    ap.add_argument("--layout", choices=["drive", "tree"], default=None)
    ap.add_argument("--dest", type=Path, default=DW_ROOT, help="data_warehouse directory to restore into")
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--task", action="append", help="restrict to task id(s)")
    ap.add_argument("--include-optional", action="store_true", help="also checkpoints, logs and OOF/test prediction files")
    ap.add_argument("--archive-conflicts", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true", help="only check the destination against the manifest")
    ap.add_argument("--log", type=Path, default=None)
    a = ap.parse_args(argv)
    m = load_manifest(a.manifest)
    src = None if a.verify_only else a.source
    if src is not None and not src.exists():
        raise RestoreError(f"source not found: {src}")
    layout = (a.layout or detect_layout(src)) if src else None
    items = plan(m, a.dest, src, layout, a.task, a.include_optional)
    items = execute(items, a.dest, a.archive_conflicts, a.dry_run or a.verify_only)
    s, bad = summarise(items)
    report = {"time": datetime.now().isoformat(timespec="seconds"), "source": str(src) if src else None, "layout": layout,
              "dest": str(a.dest), "dry_run": a.dry_run, "verify_only": a.verify_only, "summary": s, "items": items}
    log = a.log or (a.dest / "artifacts" / "restore_log.json")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(s))
    for b in bad[:25]:
        print(f"  {b['action']:<20} {b['path']}  {b.get('result', b.get('note', ''))}")
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RestoreError as e:
        print(f"RESTORE ERROR: {e}", file=sys.stderr)
        sys.exit(2)
