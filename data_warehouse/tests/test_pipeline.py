"""Fast automated tests (small synthetic sample). Run from the data_warehouse folder:  python -m pytest -q"""
from pathlib import Path

import pandas as pd

from pipelines.common import RAW_UCI_FILE, UCI_EXPECTED_SHA256, sha256_of
from pipelines.synthetic.generate import generate
from pipelines import uci_processing


def test_original_uci_file_is_unchanged():
    assert sha256_of(RAW_UCI_FILE) == UCI_EXPECTED_SHA256


def test_uci_processing_keeps_records_separate_and_complete():
    tables = uci_processing.build_tables(uci_processing.load_raw())
    s = tables["uci_students"]
    assert len(s) == 4424 and set(s["data_source"]) == {"UCI"}
    assert s["outcome_at_normal_duration"].value_counts().to_dict() == {"GRADUATED": 2209, "DROPPED_OUT": 1421, "STILL_ENROLLED": 794}
    assert len(tables["uci_semester_results"]) == 2 * 4424
    assert not {"term_id", "admission_date", "programme_id", "school_id"} & set(s.columns)


def test_same_seed_is_reproducible_and_other_seed_differs(tmp_path: Path):
    ov = {"meta.target_students": 250}
    a = generate(tmp_path / "a", overrides=ov)
    b = generate(tmp_path / "b", overrides=ov)
    c = generate(tmp_path / "c", overrides={**ov, "meta.random_seed": 7})
    assert {k: v["sha256"] for k, v in a["files"].items()} == {k: v["sha256"] for k, v in b["files"].items()}
    assert a["files"]["registrar/students.csv"]["sha256"] != c["files"]["registrar/students.csv"]["sha256"]


def test_small_sample_core_rules(tmp_path: Path):
    generate(tmp_path, overrides={"meta.target_students": 250})
    te = pd.read_csv(tmp_path / "registrar/term_enrolments.csv")
    sp = pd.read_csv(tmp_path / "registrar/student_programmes.csv", keep_default_na=False)
    assert not te.duplicated(["student_id", "term_id"]).any()
    assert not te["term_id"].str.startswith("2027").any()
    last = te.groupby("student_programme_id")["term_id"].last()
    grads = sp[sp["outcome"] == "GRADUATED"]
    seq = te.drop_duplicates("term_id").set_index("term_id")["term_sequence"]
    max_seq = te.groupby("student_programme_id")["term_sequence"].max()
    assert all(max_seq[r.student_programme_id] == seq[r.outcome_term_id] for r in grads.itertuples())
    assert set(pd.read_csv(tmp_path / "registrar/students.csv")["data_source"]) == {"SYNTHETIC"}
