"""Shared paths, labels, data loading and the dataset-card format for feature engineering."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from ..common import PROCESSED_UCI_DIR, PROJECT_ROOT, RAW_UCI_FILE, SYNTHETIC_DIR

MODELING_DIR = PROJECT_ROOT / "data" / "processed" / "modeling"
DW = PROJECT_ROOT / "data_warehouse"
REPORTS_DIR = DW / "reports"
MODELS_DIR = DW / "models"
EXPERIMENTS_DIR = DW / "experiments"

SYN_BANNER = "SYNTHETIC DEMONSTRATION DATA — NOT REAL UNIVERSITY PREDICTIONS."
UCI_BANNER = ("UCI RESEARCH DATA (Realinho et al., 2021, CC BY 4.0): a public Portuguese higher-education dataset. "
              "Results describe that dataset only, not this university.")


@dataclass
class DatasetCard:
    """Everything needed to train and audit one task-specific modelling dataset."""
    name: str
    zone: str                       # UCI | SYNTHETIC
    task: str                       # classification | regression | survival | forecasting
    prediction_point: str
    target_definition: str
    targets: list[str]
    features_numeric: list[str]
    features_categorical: list[str]
    id_columns: list[str]
    excluded_leakage_columns: dict[str, str]     # column -> reason it is excluded
    population: str
    split: str
    notes: list[str] = field(default_factory=list)
    rows: int = 0

    @property
    def features(self) -> list[str]:
        return self.features_numeric + self.features_categorical

    def to_json(self) -> dict:
        d = asdict(self)
        d["features"] = self.features
        return d


def save_dataset(df: pd.DataFrame, card: DatasetCard, out_dir: Path = MODELING_DIR) -> Path:
    zone_dir = out_dir / card.zone.lower()
    zone_dir.mkdir(parents=True, exist_ok=True)
    card.rows = int(len(df))
    path = zone_dir / f"{card.name}.csv"
    df.to_csv(path, index=False, lineterminator="\n", float_format="%.6f")
    (zone_dir / f"{card.name}.card.json").write_text(json.dumps(card.to_json(), indent=2, default=str), encoding="utf-8")
    return path


def load_dataset(name: str, zone: str, out_dir: Path = MODELING_DIR) -> tuple[pd.DataFrame, dict]:
    d = out_dir / zone.lower()
    card = json.loads((d / f"{name}.card.json").read_text(encoding="utf-8"))
    df = pd.read_csv(d / f"{name}.csv", low_memory=False, keep_default_na=False, na_values=[""])
    return df, card


def read_synthetic(syn_dir: Path = SYNTHETIC_DIR) -> dict[str, pd.DataFrame]:
    def r(rel):
        return pd.read_csv(Path(syn_dir) / f"{rel}.csv", low_memory=False, keep_default_na=False, na_values=[""])
    names = ["reference/academic_terms", "reference/programmes", "reference/level_rules", "registrar/students",
             "registrar/student_programmes", "registrar/term_enrolments", "registrar/course_enrolments",
             "registrar/academic_standing", "registrar/retention_cohort_members", "registrar/graduation_records",
             "registrar/cohorts", "registrar/cohort_members", "admissions/applications", "admissions/applicants",
             "finance/charges", "finance/payments", "finance/financial_holds", "finance/registration_blocks"]
    t = {n.split("/")[1]: r(n) for n in names}
    t["manifest"] = json.loads((Path(syn_dir) / "manifest.json").read_text())
    terms = t["academic_terms"]
    for c in ("start_date", "census_date", "end_date"):
        terms[c] = pd.to_datetime(terms[c])
    return t


def read_uci() -> pd.DataFrame:
    return pd.read_csv(PROCESSED_UCI_DIR / "uci_source_records.csv")


def data_version(syn_dir: Path = SYNTHETIC_DIR) -> dict:
    m = json.loads((Path(syn_dir) / "manifest.json").read_text())
    return {"synthetic_generation_run_id": m.get("generation_run_id"),
            "synthetic_manifest_sha256": hashlib.sha256((Path(syn_dir) / "manifest.json").read_bytes()).hexdigest(),
            "uci_raw_sha256": hashlib.sha256(RAW_UCI_FILE.read_bytes()).hexdigest(),
            "as_of_date": m["as_of_date"]}
