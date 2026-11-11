"""Zone C reference data: calendar, schools, programmes, courses, rules, fees, roles, servers.

Everything here is a PLACEHOLDER (data_source = 'SYNTHETIC', verification_status = 'PLACEHOLDER')
until it is replaced by verified university information (data_source = 'EXTERNAL_REFERENCE').
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PLACEHOLDER = {"data_source": "SYNTHETIC", "verification_status": "PLACEHOLDER",
               "source_reference": "", "verified_on": "", "verified_by": ""}
SEASON_CODE = {"FALL": "FA", "SPRING": "SP", "SUMMER": "SU"}
LEVELS = ("UNDERGRADUATE", "MASTERS", "DOCTORATE")


def load_config(path: Path, overrides: dict | None = None) -> dict:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    for dotted, value in (overrides or {}).items():
        node = cfg
        *parents, leaf = dotted.split(".")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return cfg


# --------------------------------------------------------------------------- calendar
@dataclass(frozen=True)
class Term:
    seq: int
    term_id: str
    season: str
    calendar_year: int
    academic_year: str
    start: date
    census: date
    end: date
    status: str          # COMPLETED / IN_PROGRESS / FUTURE (relative to as_of_date)

    @property
    def is_regular(self) -> bool:
        return self.season in ("FALL", "SPRING")


def _md(year: int, md: str) -> date:
    m, d = md.split("-")
    return date(year, int(m), int(d))


def build_terms(cfg: dict) -> list[Term]:
    as_of = date.fromisoformat(cfg["meta"]["as_of_date"])
    first, last = cfg["meta"]["first_term"], cfg["meta"]["calendar_end_term"]
    terms, seq, year, season = [], 1, int(first[:4]), {"FA": "FALL", "SP": "SPRING", "SU": "SUMMER"}[first[4:]]
    order = ["SPRING", "SUMMER", "FALL"]
    while True:
        c = cfg["calendar"][season.lower()]
        start, census, end = _md(year, c["start"]), _md(year, c["census"]), _md(year, c["end"])
        ay_start = year if season == "FALL" else year - 1
        status = "COMPLETED" if end <= as_of else ("IN_PROGRESS" if start <= as_of else "FUTURE")
        tid = f"{year}{SEASON_CODE[season]}"
        terms.append(Term(seq, tid, season, year, f"{ay_start}/{str(ay_start + 1)[2:]}", start, census, end, status))
        if tid == last:
            break
        i = order.index(season)
        season = order[(i + 1) % 3]
        if season == "SPRING":
            year += 1
        seq += 1
    return terms


def terms_table(terms: list[Term], cfg: dict) -> list[dict]:
    last_adm = cfg["meta"]["last_admission_term"]
    last_seq = next(t.seq for t in terms if t.term_id == last_adm)
    summer_ok = cfg["calendar"]["summer_admission_enabled"]
    as_of = date.fromisoformat(cfg["meta"]["as_of_date"])
    rows = []
    for t in terms:
        census_passed = t.census <= as_of
        reporting = ("COMPLETED_TERM" if t.status == "COMPLETED" else
                     "CENSUS_SNAPSHOT_ONLY" if census_passed else "FUTURE_NOT_REPORTABLE")
        rows.append({
            "term_id": t.term_id, "term_sequence": t.seq, "season": t.season, "calendar_year": t.calendar_year,
            "academic_year": t.academic_year, "start_date": t.start, "census_date": t.census, "end_date": t.end,
            "term_status": t.status, "reporting_status": reporting, "census_passed": census_passed,
            "grades_final_available": t.status == "COMPLETED", "is_regular_term": t.is_regular,
            "accepts_admissions": (t.season != "SUMMER" or summer_ok),
            "has_enrolment_data": t.seq <= last_seq,
            "in_completed_reporting": t.status == "COMPLETED",
            **PLACEHOLDER,
        })
    return rows


def academic_years_table(terms: list[Term], cfg: dict) -> list[dict]:
    as_of = date.fromisoformat(cfg["meta"]["as_of_date"])
    out = []
    for ay in sorted({t.academic_year for t in terms}):
        ts = [t for t in terms if t.academic_year == ay]
        start, end = min(t.start for t in ts), max(t.end for t in ts)
        out.append({"academic_year": ay, "start_date": start, "end_date": end,
                    "terms": "|".join(t.term_id for t in sorted(ts, key=lambda x: x.seq)),
                    "year_status": "COMPLETED" if end <= as_of else ("IN_PROGRESS" if start <= as_of else "FUTURE"),
                    **PLACEHOLDER})
    return out


# --------------------------------------------------------------------------- schools & programmes
SCHOOLS = [
    ("SBUS", "School of Business and Management"),
    ("SENG", "School of Engineering and Computing"),
    ("SHLT", "School of Health Sciences"),
    ("SEDU", "School of Education and Social Sciences"),
    ("SART", "School of Arts, Humanities and Media"),
]
# (code, school, level, name, delivery modes offered, relative popularity)
PROGRAMMES = [
    ("UG-BBA", "SBUS", "UNDERGRADUATE", "BBA Business Administration", "FACE_TO_FACE|ONLINE", 1.4),
    ("UG-ACF", "SBUS", "UNDERGRADUATE", "BSc Accounting and Finance", "FACE_TO_FACE|ONLINE", 1.0),
    ("UG-CS",  "SENG", "UNDERGRADUATE", "BSc Computer Science", "FACE_TO_FACE|ONLINE", 1.3),
    ("UG-CE",  "SENG", "UNDERGRADUATE", "BEng Civil Engineering", "FACE_TO_FACE", 0.7),
    ("UG-IT",  "SENG", "UNDERGRADUATE", "BSc Information Technology", "FACE_TO_FACE|ONLINE", 1.0),
    ("UG-NUR", "SHLT", "UNDERGRADUATE", "BSc Nursing", "FACE_TO_FACE", 1.2),
    ("UG-PH",  "SHLT", "UNDERGRADUATE", "BSc Public Health", "FACE_TO_FACE|ONLINE", 0.7),
    ("UG-EDU", "SEDU", "UNDERGRADUATE", "BEd Primary Education", "FACE_TO_FACE", 0.8),
    ("UG-PSY", "SEDU", "UNDERGRADUATE", "BA Psychology", "FACE_TO_FACE|ONLINE", 1.0),
    ("UG-COM", "SART", "UNDERGRADUATE", "BA Communication and Media", "FACE_TO_FACE|ONLINE", 0.8),
    ("UG-ENG", "SART", "UNDERGRADUATE", "BA English and Literature", "FACE_TO_FACE", 0.5),
    ("MA-MBA", "SBUS", "MASTERS", "Master of Business Administration", "FACE_TO_FACE|ONLINE", 1.5),
    ("MA-FIN", "SBUS", "MASTERS", "MSc Finance", "FACE_TO_FACE", 0.7),
    ("MA-DS",  "SENG", "MASTERS", "MSc Data Science", "FACE_TO_FACE|ONLINE", 1.3),
    ("MA-SE",  "SENG", "MASTERS", "MSc Software Engineering", "FACE_TO_FACE|ONLINE", 0.8),
    ("MA-MPH", "SHLT", "MASTERS", "Master of Public Health", "FACE_TO_FACE|ONLINE", 0.9),
    ("MA-NUR", "SHLT", "MASTERS", "MSc Nursing", "FACE_TO_FACE", 0.6),
    ("MA-MED", "SEDU", "MASTERS", "MEd Educational Leadership", "FACE_TO_FACE|ONLINE", 0.8),
    ("MA-CP",  "SEDU", "MASTERS", "MA Counselling Psychology", "FACE_TO_FACE", 0.6),
    ("MA-COM", "SART", "MASTERS", "MA Strategic Communication", "FACE_TO_FACE|ONLINE", 0.5),
    ("DR-DBA", "SBUS", "DOCTORATE", "Doctor of Business Administration", "FACE_TO_FACE|ONLINE", 0.8),
    ("DR-CS",  "SENG", "DOCTORATE", "PhD Computer Science", "FACE_TO_FACE", 1.0),
    ("DR-HS",  "SHLT", "DOCTORATE", "PhD Health Sciences", "FACE_TO_FACE", 0.9),
    ("DR-EDU", "SEDU", "DOCTORATE", "PhD Education", "FACE_TO_FACE|ONLINE", 0.8),
]


def schools_table() -> list[dict]:
    return [{"school_id": code, "school_code": code, "name": name, "display_name": f"{name} [synthetic placeholder]",
             "is_placeholder": True, **PLACEHOLDER} for code, name in SCHOOLS]


def programmes_table(cfg: dict) -> list[dict]:
    out = []
    for code, school, level, name, modes, weight in PROGRAMMES:
        lv = cfg["levels"][level]
        out.append({
            "programme_id": code, "programme_code": code, "name": name,
            "display_name": f"{name} [synthetic placeholder]", "is_placeholder": True, "school_id": school, "level": level,
            "delivery_modes_offered": modes, "credits_required": lv["credits_required"],
            "normal_duration_years_override": "", "graduation_window_years_override": "",
            "intake_weight": weight, **PLACEHOLDER,
        })
    return out


def courses_table(cfg: dict) -> list[dict]:
    """Course catalogue per programme. Titles are generic placeholders."""
    out = []
    for code, _school, level, name, _modes, _w in PROGRAMMES:
        lv = cfg["levels"][level]
        short = code.split("-")[1]
        if level == "UNDERGRADUATE":
            n_courses, years = 44, 4
        elif level == "MASTERS":
            n_courses, years = 14, 2
        else:
            n_courses, years = 10, 2
        for i in range(n_courses):
            year_level = 1 + (i * years) // n_courses
            num = year_level * 100 + (i % (n_courses // years)) + 1
            cid = f"{short}{'' if level == 'UNDERGRADUATE' else level[0]}{num}"
            out.append({
                "course_id": cid, "programme_id": code, "course_code": cid,
                "title": f"{name.split(' ', 1)[1]} module {num}", "credits": lv["course_credits"],
                "year_level": year_level, "course_type": "COURSEWORK", **PLACEHOLDER,
            })
        if level == "DOCTORATE":
            out.append({"course_id": f"{short}D900", "programme_id": code, "course_code": f"{short}D900",
                        "title": "Doctoral research (variable credit)", "credits": 0, "year_level": 9,
                        "course_type": "RESEARCH", **PLACEHOLDER})
    return out


def grading_scheme_table(cfg: dict) -> list[dict]:
    g = cfg["grading"]
    return [{"grading_scheme_id": "DEMO4", "name": g["name"], "display_label": g["display_label"],
             "scale_min": 0.0, "scale_max": 4.0,
             "letter_points": json.dumps(dict(zip(g["letters"], g["points"]))),
             "non_gpa_grades": "W (withdrawn), IP (in progress)", **PLACEHOLDER}]


def level_rules_table(cfg: dict) -> list[dict]:
    out = []
    for level in LEVELS:
        lv = cfg["levels"][level]
        out.append({"rule_set_id": "DEMO-RULES-1", "level": level,
                    "normal_duration_years": lv["normal_duration_years"],
                    "graduation_window_years": lv["graduation_window_years"],
                    "min_years_to_graduate": lv["min_years_to_graduate"],
                    "credits_required": lv["credits_required"], "pass_points": lv["pass_points"],
                    "good_standing_min_gpa": lv["good_standing_min_gpa"],
                    "graduation_min_gpa": lv["graduation_min_gpa"],
                    "window_basis": "PROJECT_CONFIGURED_REPORTING_ASSUMPTION",
                    "note": ("6-year Doctorate window requested for this dashboard; not verified university policy"
                             if level == "DOCTORATE" else "Reporting window requested for this dashboard; not verified policy"),
                    **PLACEHOLDER})
    return out


def rule_sets_table(cfg: dict) -> list[dict]:
    a = cfg["academic"]
    return [{
        "rule_set_id": "DEMO-RULES-1", "name": "Demonstration academic rules", "version": "1",
        "applies_to": "INSTITUTIONAL", "is_official_policy": False,
        "standing_rules": ("Evaluated after each term with final grades, using cumulative GPA (CGPA) vs the level minimum: "
                           "GOOD/none -> WARNING if CGPA below min; WARNING -> PROBATION if CGPA still below; "
                           "PROBATION -> DISMISSED if CGPA and term GPA both below, stays PROBATION if only CGPA below; "
                           "any -> GOOD when CGPA at or above min."),
        "withdrawal_rule_id": a["withdrawal_rule_id"], "withdrawal_rule_status": a["withdrawal_rule_status"],
        "withdrawal_rule": (f"Synthetic business rule: more than {a['max_consecutive_missed_terms']} consecutive missed "
                            "regular terms records an UNOFFICIAL withdrawal at the next missed term's census; "
                            "admission history is never modified"),
        "poor_performance_rule": (f"Term GPA below level good-standing minimum OR passed share of graded credits below "
                                  f"{cfg['reporting']['poor_performance_pass_ratio_below']}"),
        "max_consecutive_missed_terms": a["max_consecutive_missed_terms"],
        "summer_counts_as_expected_term": a["summer_counts_as_expected_term"],
        "summer_admission_enabled": cfg["calendar"]["summer_admission_enabled"],
        "gpa_rule": "Credit-weighted mean of grade points of all graded attempts (W and IP excluded), per student programme",
        "conferral_rule": a["conferral"], **PLACEHOLDER,
    }]


def fee_schedule_table(cfg: dict, terms: list[Term]) -> list[dict]:
    f = cfg["finance"]
    years = sorted({int(t.academic_year[:4]) for t in terms})
    out = []
    for y in years:
        for level in LEVELS:
            factor = (1 + f["annual_fee_increase"]) ** (y - years[0])
            out.append({"academic_year": f"{y}/{str(y + 1)[2:]}", "level": level,
                        "tuition_per_credit": round(f["tuition_per_credit_2016"][level] * factor, 2),
                        "registration_fee": f["registration_fee"], "technology_fee": f["technology_fee"],
                        "online_fee_per_credit": f["online_fee_per_credit"],
                        "currency_code": cfg["meta"]["currency_code"], **PLACEHOLDER})
    return out


ROLES = [
    ("STUDENT", "Student self-service", "PORTAL,LMS"),
    ("ADMISSIONS_OFFICER", "Admissions staff", "ADMISSIONS"),
    ("REGISTRAR_OFFICER", "Registrar staff", "REGISTRAR"),
    ("FINANCE_OFFICER", "Finance staff", "FINANCE"),
    ("IT_ADMINISTRATOR", "IT operations", "IT"),
    ("SYSTEM_ADMINISTRATOR", "Platform administration", "ADMIN,IT"),
    ("EXECUTIVE_VIEWER", "Management dashboards and reports", "MANAGEMENT"),
    ("DATA_ENGINEER", "Data warehouse operations", "DATA_WAREHOUSE"),
    ("FACULTY", "Teaching staff", "REGISTRAR_READ,LMS"),
]
DEPARTMENT_ROLE = {"ADMISSIONS": "ADMISSIONS_OFFICER", "REGISTRAR": "REGISTRAR_OFFICER", "FINANCE": "FINANCE_OFFICER",
                   "IT": "IT_ADMINISTRATOR", "ADMIN": "SYSTEM_ADMINISTRATOR", "MANAGEMENT": "EXECUTIVE_VIEWER",
                   "DATA_WAREHOUSE": "DATA_ENGINEER", "FACULTY": "FACULTY"}


def roles_table() -> list[dict]:
    return [{"role_code": r, "description": d, "module_access": m, **PLACEHOLDER} for r, d, m in ROLES]


SERVERS = [
    ("srv-auth-01", "Authentication service", "AUTH"),
    ("srv-web-01", "Student and staff portal", "PORTAL"),
    ("srv-sis-01", "Student information system (node 1)", "SIS"),
    ("srv-sis-02", "Student information system (node 2)", "SIS"),
    ("srv-lms-01", "Learning management system", "LMS"),
    ("srv-adm-01", "Admissions application portal", "ADMISSIONS"),
    ("srv-fin-01", "Finance and billing system", "FINANCE"),
    ("srv-db-01", "Primary database server", "DATABASE"),
    ("srv-dw-01", "Data warehouse ETL server", "DATA_WAREHOUSE"),
    ("srv-bak-01", "Backup server", "BACKUP"),
]


def servers_table() -> list[dict]:
    return [{"server_id": s, "description": d, "system": sysname, "environment": "PRODUCTION", **PLACEHOLDER}
            for s, d, sysname in SERVERS]


# --------------------------------------------------------------------------- code lists (reference domains)
COUNTRY_LABELS = {"IND": "India", "NGA": "Nigeria", "CHN": "China", "USA": "United States of America",
                  "GBR": "United Kingdom", "BRA": "Brazil", "KEN": "Kenya", "PAK": "Pakistan", "DEU": "Germany",
                  "VNM": "Viet Nam", "GHA": "Ghana", "PHL": "Philippines", "MEX": "Mexico", "EGY": "Egypt"}


def nationalities_table(cfg: dict) -> list[dict]:
    home = cfg["demographics"]["home_country_iso3"]
    rows = [{"nationality_iso3": home, "label": "Home country (placeholder - not configured)",
             "residency_status": "DOMESTIC", **PLACEHOLDER}]
    for code in cfg["demographics"]["international_countries"]:
        rows.append({"nationality_iso3": code, "label": COUNTRY_LABELS.get(code, code),
                     "residency_status": "INTERNATIONAL", **PLACEHOLDER})
    return rows


def code_table(key: str, values: list[tuple[str, str]]) -> list[dict]:
    return [{key: v, "description": d, **PLACEHOLDER} for v, d in values]


CODE_LISTS = {
    "gender_categories": ("gender", [("FEMALE", "Female"), ("MALE", "Male"), ("ANOTHER_GENDER", "Another gender"),
                                     ("NOT_DISCLOSED", "Not disclosed")]),
    "delivery_modes": ("delivery_mode", [("FACE_TO_FACE", "Face-to-face (on campus)"), ("ONLINE", "Online")]),
    "attendance_loads": ("study_load", [("FULL_TIME", "Full-time load"), ("PART_TIME", "Part-time load")]),
    "academic_standing_codes": ("standing", [
        ("GOOD", "Good academic standing (synthetic rule)"), ("WARNING", "Academic warning (synthetic rule)"),
        ("PROBATION", "Academic probation (synthetic rule)"), ("DISMISSED", "Academic dismissal (synthetic rule)"),
        ("NOT_EVALUATED", "No graded courses yet in this admission")]),
    "student_status_codes": ("status_code", [
        ("ADMITTED", "Admission to a programme recorded"), ("STOPPED_OUT", "First missed regular term (on gap)"),
        ("RETURNED", "Re-enrolled after a gap"), ("WITHDRAWN", "Withdrawal recorded"),
        ("DISMISSED", "Academic dismissal recorded"), ("CHANGED_PROGRAMME", "Left programme for another programme"),
        ("GRADUATED", "Degree conferred")]),
}
