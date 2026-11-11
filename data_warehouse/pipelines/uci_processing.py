"""Clean the original UCI file into UCI-only tables (Zone A).

Rules:
- The raw file is read, never written. Its SHA-256 must match the known fingerprint.
- No admission dates, terms, graduation dates, schools, delivery modes or university
  programmes are created for UCI students.
- UCI course categories are kept as UCI categories, not university programmes.

Usage (from the data_warehouse folder):  python -m pipelines.uci_processing
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import PROCESSED_UCI_DIR, RAW_UCI_FILE, UCI_EXPECTED_SHA256, sha256_of, write_csv, write_json

# ---- Code labels from the UCI dataset documentation (id 697). -------------------------------
# Only code lists whose labels are documented with confidence are loaded. Parent occupation and
# parent qualification codes are kept as raw codes (labels can be added later from the
# documentation as EXTERNAL_REFERENCE).
COURSE = {
    33: "Biofuel Production Technologies", 171: "Animation and Multimedia Design",
    8014: "Social Service (evening attendance)", 9003: "Agronomy", 9070: "Communication Design",
    9085: "Veterinary Nursing", 9119: "Informatics Engineering", 9130: "Equinculture",
    9147: "Management", 9238: "Social Service", 9254: "Tourism", 9500: "Nursing",
    9556: "Oral Hygiene", 9670: "Advertising and Marketing Management",
    9773: "Journalism and Communication", 9853: "Basic Education",
    9991: "Management (evening attendance)",
}
NATIONALITY = {
    1: "Portuguese", 2: "German", 6: "Spanish", 11: "Italian", 13: "Dutch", 14: "English",
    17: "Lithuanian", 21: "Angolan", 22: "Cape Verdean", 24: "Guinean", 25: "Mozambican",
    26: "Santomean", 32: "Turkish", 41: "Brazilian", 62: "Romanian", 100: "Moldova (Republic of)",
    101: "Mexican", 103: "Ukrainian", 105: "Russian", 108: "Cuban", 109: "Colombian",
}
MARITAL = {1: "Single", 2: "Married", 3: "Widower", 4: "Divorced", 5: "Facto union", 6: "Legally separated"}
APPLICATION_MODE = {
    1: "1st phase - general contingent", 2: "Ordinance No. 612/93",
    5: "1st phase - special contingent (Azores Island)", 7: "Holders of other higher courses",
    10: "Ordinance No. 854-B/99", 15: "International student (bachelor)",
    16: "1st phase - special contingent (Madeira Island)", 17: "2nd phase - general contingent",
    18: "3rd phase - general contingent", 26: "Ordinance No. 533-A/99, item b2 (Different Plan)",
    27: "Ordinance No. 533-A/99, item b3 (Other Institution)", 39: "Over 23 years old",
    42: "Transfer", 43: "Change of course", 44: "Technological specialization diploma holders",
    51: "Change of institution/course", 53: "Short cycle diploma holders",
    57: "Change of institution/course (International)",
}
PREVIOUS_QUALIFICATION = {
    1: "Secondary education", 2: "Higher education - bachelor's degree", 3: "Higher education - degree",
    4: "Higher education - master's", 5: "Higher education - doctorate",
    6: "Frequency of higher education", 9: "12th year of schooling - not completed",
    10: "11th year of schooling - not completed", 12: "Other - 11th year of schooling",
    14: "10th year of schooling", 15: "10th year of schooling - not completed",
    19: "Basic education 3rd cycle (9th/10th/11th year) or equivalent",
    38: "Basic education 2nd cycle (6th/7th/8th year) or equivalent",
    39: "Technological specialization course", 40: "Higher education - degree (1st cycle)",
    42: "Professional higher technical course", 43: "Higher education - master (2nd cycle)",
}

RENAME = {
    "Marital status": "marital_status_code", "Application mode": "application_mode_code",
    "Application order": "application_order", "Course": "uci_course_code",
    "Daytime/evening attendance\t": "daytime_evening_attendance",
    "Previous qualification": "previous_qualification_code",
    "Previous qualification (grade)": "previous_qualification_grade",
    "Nacionality": "nationality_code", "Mother's qualification": "mother_qualification_code",
    "Father's qualification": "father_qualification_code", "Mother's occupation": "mother_occupation_code",
    "Father's occupation": "father_occupation_code", "Admission grade": "admission_grade",
    "Displaced": "displaced", "Educational special needs": "educational_special_needs", "Debtor": "debtor",
    "Tuition fees up to date": "tuition_fees_up_to_date", "Gender": "gender_code",
    "Scholarship holder": "scholarship_holder", "Age at enrollment": "age_at_enrollment",
    "International": "international", "Unemployment rate": "unemployment_rate",
    "Inflation rate": "inflation_rate", "GDP": "gdp", "Target": "target",
}
for _s, _n in (("1st", 1), ("2nd", 2)):
    for _k in ("credited", "enrolled", "evaluations", "approved", "grade", "without evaluations"):
        RENAME[f"Curricular units {_s} sem ({_k})"] = f"sem{_n}_{_k.replace(' ', '_')}"


def load_raw() -> pd.DataFrame:
    actual = sha256_of(RAW_UCI_FILE)
    if actual != UCI_EXPECTED_SHA256:
        raise RuntimeError(f"Original UCI file fingerprint changed ({actual}). Refusing to process.")
    df = pd.read_csv(RAW_UCI_FILE, sep=";", encoding="utf-8-sig")
    missing = set(RENAME) - set(df.columns)
    if missing or df.shape != (4424, 37):
        raise RuntimeError(f"Unexpected UCI structure: shape={df.shape}, missing={missing}")
    return df


def build_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    src = df.rename(columns=RENAME)
    src.insert(0, "uci_row_number", np.arange(1, len(src) + 1))
    uci_id = src["uci_row_number"].map(lambda n: f"UCI-{n:06d}")

    # 5.1 uci_source_records: every original value, unchanged (renamed columns only)
    source_records = src.copy()
    source_records.insert(1, "data_source", "UCI")

    # 5.2 uci_course_categories (UCI categories, NOT university programmes)
    sched = src.groupby("uci_course_code")["daytime_evening_attendance"].agg(lambda s: sorted(set(s)))
    categories = pd.DataFrame({
        "uci_course_code": list(COURSE),
        "label": list(COURSE.values()),
        "attendance_schedule": [("EVENING" if sched[c] == [0] else "DAYTIME" if sched[c] == [1] else "MIXED") for c in COURSE],
        "student_count": [int((src["uci_course_code"] == c).sum()) for c in COURSE],
        "data_source": "UCI",
        "note": "UCI dataset course category. Not a programme of this university.",
    })

    # 5.3 uci_students
    both_zero = (src["sem1_enrolled"] == 0) & (src["sem2_enrolled"] == 0)
    students = pd.DataFrame({
        "uci_student_id": uci_id,
        "uci_row_number": src["uci_row_number"],
        "data_source": "UCI",
        "gender": src["gender_code"].map({1: "MALE", 0: "FEMALE"}),
        "nationality_code": src["nationality_code"],
        "nationality_label": src["nationality_code"].map(NATIONALITY).fillna("UNKNOWN"),
        "is_international": src["international"].astype(bool),
        "marital_status_code": src["marital_status_code"],
        "marital_status_label": src["marital_status_code"].map(MARITAL).fillna("UNKNOWN"),
        "age_at_enrollment": src["age_at_enrollment"],
        "uci_course_code": src["uci_course_code"],
        "uci_course_label": src["uci_course_code"].map(COURSE),
        "attendance_schedule": src["daytime_evening_attendance"].map({1: "DAYTIME", 0: "EVENING"}),
        "application_mode_code": src["application_mode_code"],
        "application_mode_label": src["application_mode_code"].map(APPLICATION_MODE).fillna("UNKNOWN"),
        "application_order": src["application_order"],
        "previous_qualification_code": src["previous_qualification_code"],
        "previous_qualification_label": src["previous_qualification_code"].map(PREVIOUS_QUALIFICATION).fillna("UNKNOWN"),
        "previous_qualification_grade": src["previous_qualification_grade"],
        "admission_grade": src["admission_grade"],
        "scholarship_holder": src["scholarship_holder"].astype(bool),
        "debtor": src["debtor"].astype(bool),
        "tuition_fees_up_to_date": src["tuition_fees_up_to_date"].astype(bool),
        "displaced": src["displaced"].astype(bool),
        "educational_special_needs": src["educational_special_needs"].astype(bool),
        "outcome_at_normal_duration": src["target"].map({"Graduate": "GRADUATED", "Dropout": "DROPPED_OUT", "Enrolled": "STILL_ENROLLED"}),
        "dq_flags": np.where(both_zero, "NOT_EVALUATED_BOTH_SEMESTERS", ""),
    })

    # 5.4 uci_semester_results: 2 rows per student (relative semesters of year 1, NOT calendar terms)
    rows = []
    for n in (1, 2):
        en, ap = src[f"sem{n}_enrolled"], src[f"sem{n}_approved"]
        status = np.select([en == 0, ap == 0], ["NOT_EVALUATED", "NO_UNITS_PASSED"], "EVALUATED")
        flags = np.where(src[f"sem{n}_without_evaluations"] > en, "WITHOUT_EVAL_GT_ENROLLED", "")
        rows.append(pd.DataFrame({
            "uci_student_id": uci_id, "data_source": "UCI", "study_semester": n,
            "units_credited": src[f"sem{n}_credited"], "units_enrolled": en,
            "units_evaluated": src[f"sem{n}_evaluations"], "units_approved": ap,
            "units_without_evaluation": src[f"sem{n}_without_evaluations"],
            "uci_grade_raw": src[f"sem{n}_grade"],
            "uci_mean_grade_passed_units_0_20": src[f"sem{n}_grade"].where(ap > 0),
            "pass_rate": (ap / en).where(en > 0).round(4),
            "evaluation_status": status, "dq_flags": flags,
        }))
    semesters = pd.concat(rows).sort_values(["uci_student_id", "study_semester"]).reset_index(drop=True)

    lookups = pd.concat([
        pd.DataFrame({"category": cat, "code": list(m), "label": list(m.values())})
        for cat, m in [("course", COURSE), ("nationality", NATIONALITY), ("marital_status", MARITAL),
                       ("application_mode", APPLICATION_MODE), ("previous_qualification", PREVIOUS_QUALIFICATION)]
    ])
    lookups["data_source"] = "UCI"

    return {"uci_source_records": source_records, "uci_course_categories": categories,
            "uci_students": students, "uci_semester_results": semesters, "code_lookups": lookups}


def run() -> dict[str, pd.DataFrame]:
    tables = build_tables(load_raw())
    for name, t in tables.items():
        write_csv(t, PROCESSED_UCI_DIR / f"{name}.csv")
    write_json({
        "data_source": "UCI", "source_file": "data/raw/data.csv", "source_sha256": UCI_EXPECTED_SHA256,
        "tables": {k: len(v) for k, v in tables.items()},
        "note": "UCI reference zone. No dates, terms or university links are created for UCI students.",
    }, PROCESSED_UCI_DIR / "manifest.json")
    return tables


if __name__ == "__main__":
    for k, v in run().items():
        print(f"{k:24s} {len(v):6d} rows")
