"""Shared paths and small I/O helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_UCI_FILE = DATA_DIR / "raw" / "data.csv"
PROCESSED_UCI_DIR = DATA_DIR / "processed" / "uci"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
CONFIG_FILE = PROJECT_ROOT / "data_warehouse" / "config" / "synthetic_config.toml"

# Fingerprint of the original UCI download. If it ever changes, processing stops.
UCI_EXPECTED_SHA256 = "3ef126de5cefff26eb11fbb4237f1a1401cb64b488e2f1d598c23cedeb4c45ae"

DATA_SOURCES = ("UCI", "SYNTHETIC", "EXTERNAL_REFERENCE")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Deterministic CSV output (fixed line endings and float format) so hashes are reproducible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n", float_format="%.4f", encoding="utf-8")


def write_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
