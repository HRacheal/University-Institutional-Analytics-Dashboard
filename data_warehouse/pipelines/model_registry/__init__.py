"""Model registry: artifact manifest, reproducible restoration from the Google Drive backups, model loading for the
dashboard backend, and the restoration audit.

    python -m pipelines.model_registry.manifest  --drive-root <MyDrive/analytics_project_outputs>   # (re)build manifest
    python -m pipelines.model_registry.restore   --source <MyDrive/analytics_project_outputs>       # restore artifacts
    python -m pipelines.model_registry.audit     [--artifact-root <dir>]                             # load + predict audit

Nothing here trains a model. Restoration never modifies the backup source and never overwrites a differing local file
unless it is first archived (``--archive-conflicts``).
"""
from pathlib import Path

DW_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = DW_ROOT / "artifacts"
MANIFEST_PATH = ARTIFACTS_DIR / "artifact_manifest.json"
