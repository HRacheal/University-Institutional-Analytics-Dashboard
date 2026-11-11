# Data Model: Revision 4 (implemented as CSV extracts; PostgreSQL load is next)

| | |
|---|---|
| Status | Implemented and validated as CSV tables in `data/processed/uci/` (UCI) and `data/synthetic/` (SYNTHETIC). **No PostgreSQL tables have been created yet** |
| Revision | 4 (generator 1.1.0): corrects graduation-window labelling, Fall 2026 reporting status and the missed-term withdrawal rule; adds reference code tables, status history, retention cohort membership, graduation records, generation-run lineage and a documented schema (§11). Revision 3 added the departmental tables and C1–C10 |
| Validation | 476 / 476 checks passed, plus 31 / 31 planted-error tests detected (`data/synthetic/reports/data_quality_report.md`) |
| Policy notice | Every school, programme, course, calendar date, fee, grading scheme and academic rule is a **PLACEHOLDER** (`data_source = SYNTHETIC`, `verification_status = PLACEHOLDER`). None is an official university rule |

---

## 1. Three zones that never mix

| Zone | Contents | `data_source` | Location |
|---|---|---|---|
| **A. UCI reference** | The real UCI dataset (4,424 students, year 1 only, undated) | `UCI` | `data/processed/uci/` |
| **B. Institutional** | 5,000 synthetic students and all their departmental records | `SYNTHETIC` | `data/synthetic/{admissions,registrar,finance,it,data_warehouse}/` |
| **C. Reference & configuration** | Calendar, schools, programmes, courses, grading, rules, fees, roles, servers | `SYNTHETIC` + `PLACEHOLDER` now; `EXTERNAL_REFERENCE` + `VERIFIED` once sourced | `data/synthetic/reference/` → later `data/external_reference/` |

- **No key links Zone A to Zone B.** UCI students have no terms, dates, programmes, schools or delivery modes.
- UCI course categories (`uci_course_categories`) are **not** university programmes (D3).
- Dashboard rule: UCI panels and institutional panels are separate, and their totals are never added together.

Field origin tags: **UCI** = original value · **UCI→** = calculated from UCI · **SYN** = generated · **REF** = reference/config · **SYS** = system (IDs, timestamps).

---

## 2. Relationships

```
ZONE C  academic_terms   schools ──< programmes ──< courses   grading_schemes   rule_sets ──< level_rules
        fee_schedules (level × academic year)    roles    servers

ZONE B
 ADMISSIONS   applicants ──< applications >── programmes, academic_terms (entry term)
                   │               │ (admitted & enrolled)
 REGISTRAR    students ──< student_programmes ──< term_enrolments ──< course_enrolments >── courses
                   │        │   └ previous_student_programme_id (change / next degree / readmission)
                   │        │              └──< academic_standing >── rule_sets
                   │        └──< cohort_members >── cohorts >── academic_terms
 FINANCE           ├──< charges (per term enrolment) ── payments ── financial_holds ── registration_blocks
                   └── account_balances (snapshot at as-of date)
 IT           user_accounts (person_id = student_id | staff_id) ──< account_status_events
                   └──< login_events >── servers ──< server_status_daily, incidents      staff
 WAREHOUSE    sync_runs (one per source system per night)

ZONE A  uci_source_records ─1:1─ uci_students ──< uci_semester_results;  uci_students >── uci_course_categories;  code_lookups

A ──< B : one A has many B
```

---

## 3. Zone B tables by department (implemented)

### 3.1 Admissions
| Table | Key | Main columns | Notes |
|---|---|---|---|
| `applicants` | applicant_id `SYN-APL-…` | gender, nationality_iso3, residency_status, birth_year | People who applied. 13,320 rows |
| `applications` | application_id `SYN-APP-…` | applicant_id, student_id (if enrolled), programme_id, level, entry_term_id, application_type (NEW / NEXT_DEGREE / READMISSION), submitted_date, decision (ADMITTED, REJECTED, ADMITTED_DECLINED, WITHDRAWN_BY_APPLICANT, WAITLISTED_NOT_OFFERED, PENDING), decision_date, admission_score, enrolled | Intake = admitted and enrolled. Spring 2027 applications are a future pipeline, never enrolled |

### 3.2 Registrar
| Table | Key | Main columns | Notes |
|---|---|---|---|
| `students` | student_id `SYN-nnnnnn` | applicant_id, gender, nationality_iso3, residency_status, birth_year | No names or birth dates. First admission term is *calculated*, not stored |
| `student_programmes` | student_programme_id | student_id, programme_id, level, school_id, entry_term_id, admission_date, entry_type (FIRST_ADMISSION / PROGRAMME_CHANGE / NEXT_DEGREE / READMISSION), previous_student_programme_id, application_id, credits_transferred_in, scholarship_pct, **outcome** (ACTIVE / GRADUATED / CHANGED_PROGRAMME / WITHDRAWN / DISMISSED), outcome_term_id, outcome_date, outcome_recorded_date, withdrawal_type (FORMAL / UNOFFICIAL), exit_reason | One row per admission. Graduation lives here only (one fact, one place) |
| `term_enrolments` | term_enrolment_id | student_programme_id, student_id, programme_id, **school_id**, level, term_id, **academic_year**, study_term_number, **delivery_mode** (ONLINE / FACE_TO_FACE), **study_load** (FULL_TIME / PART_TIME), credits_attempted, credits_earned, gpa_credits, term_gpa, cumulative_gpa, cumulative_credits_earned, **passed_credit_ratio**, **poor_performance_flag**, grades_final, withdrew_during_term, **prior_gap_terms** | Unique (student_id, term_id). Fall 2026 rows have no grades, GPA or flags yet (census snapshot only) |
| `course_enrolments` | course_enrolment_id | term_enrolment_id, course_id, credits, attempt_number, grade_letter (A…F, W, IP), grade_points, grade_status, counts_in_gpa, credits_earned | The basis of every GPA |
| `academic_standing` | standing_id | term_enrolment_id, rule_set_id, standing (GOOD / WARNING / PROBATION / DISMISSED / NOT_EVALUATED), reason_code, cumulative_gpa, term_gpa, min_gpa | Calculated, never typed in. Exactly one row per **completed** term enrolment; a term with only withdrawn courses carries the previous standing forward |
| `cohorts` | cohort_id | cohort_type (INSTITUTIONAL / LEVEL_ENTRY), entry_term_id, level, size_at_census, frozen_at | 124 cohorts |
| `cohort_members` | cohort_id + student_id | student_programme_id, level_at_entry, programme_at_entry, delivery_mode_at_entry, study_load_at_entry | Attributes frozen at census |
| `student_status_history` | status_event_id | student_id, student_programme_id, status_code (ADMITTED / STOPPED_OUT / RETURNED / WITHDRAWN / DISMISSED / CHANGED_PROGRAMME / GRADUATED), term_id, event_date, status_after, rule_reference | Append-only. The admission event is never overwritten; withdrawals are new events |
| `retention_cohort_members` | retention_record_id | comparison_type (FIRST_YEAR_COHORT / FALL_TO_FALL / SPRING_TO_SPRING / SUMMER_TO_SUMMER), base/compare term and census dates, student_id, base programme/school/level/mode/load, is_final, reporting_label, status_at_compare, compare_programme_id, outcome_category, institutionally_retained, programme_retained, completed_before_compare | One row per student per comparison; the auditable basis of every retention rate |
| `graduation_records` | graduation_record_id | cohort_id (LEVEL_ENTRY), student_id, level, entry term, original admission date, programme and school at entry, window_years, window_end_date, window_basis, cohort_mature, graduation_status, graduated programme, graduation term and date, time_to_degree_years, enrolled and gap terms, graduated_within_window, graduation_eligible_by_rules, counts_in_final_rate | One row per student per level; graduates stay separate from enrolled students |

### 3.3 Finance
| Table | Main columns | Rule |
|---|---|---|
| `charges` | student_id, student_programme_id, term_id, charge_type (TUITION, REGISTRATION_FEE, TECHNOLOGY_FEE, ONLINE_LEARNING_FEE, SCHOLARSHIP < 0), amount, charge_date, due_date, currency_code | Billed only for actual term enrolments. Due = census + 14 days |
| `payments` | student_id, term_id, payment_date, amount, method, payment_type (SCHEDULED / HOLD_RESOLUTION) | Nothing after the as-of date |
| `financial_holds` | student_id, placed_date, released_date, past_due_at_placement, status_as_of | Placed 30 days after the due date if past-due > 100. Released when past-due ≤ 100 |
| `registration_blocks` | student_id, student_programme_id, term_id, registration_date, reason | A held student who doesn't pay misses that term (the gap is recorded) |
| `account_balances` | total_charged, total_paid, outstanding_balance, past_due_balance, has_active_hold | Snapshot at 2026-11-10 |

### 3.4 IT
| Table | Main columns | Rule |
|---|---|---|
| `user_accounts` | account_id, username, account_type (STUDENT / STAFF), person_id, role_code, department, created_date, status_as_of, mfa_enabled | One per student and per staff member |
| `account_status_events` | account_id, event (ACTIVATED / DISABLED / REACTIVATED), event_date | Created at admission decision. Disabled 90 days after leaving or 180 days after graduating. Reactivated on readmission or next degree |
| `staff` | staff_id, department, role_code, hire_date, end_date | 140 synthetic staff across 8 departments |
| `login_events` | account_id, event_time, system (LMS / PORTAL / SIS / ADMISSIONS / FINANCE / DATA_WAREHOUSE), server_id, success, failure_reason, channel | Last 180 days only (placeholder log retention) |
| `server_status_daily` | server_id, status_date, status, uptime_pct, downtime_minutes, cpu_avg_pct, memory_avg_pct | 10 servers × 180 days |
| `incidents` | server_id, severity, started_at, resolved_at, downtime_minutes | One per non-operational server-day |

### 3.5 Data Warehouse
| Table | Main columns | Rule |
|---|---|---|
| `generation_runs` | generation_run_id, generator_version, random_seed, config_sha256, as_of_date, first/last term, target_students, label | One row per generation; every synthetic row points to it |
| `sync_runs` | extracted_system (ADMISSIONS / REGISTRAR / FINANCE / IT), run_date, status, extract_from_date, extract_to_date, rows_extracted, failure_reason | Nightly. Fails on ETL/database outage days. The next success extracts all pending days. Row counts = records that really changed |

## 4. Zone C reference tables (all PLACEHOLDER)
`academic_terms` (33 terms Fall 2016 – Summer 2027, with term_status COMPLETED / IN_PROGRESS / FUTURE, **reporting_status** COMPLETED_TERM / CENSUS_SNAPSHOT_ONLY / FUTURE_NOT_REPORTABLE, census_passed, grades_final_available, has_enrolment_data, in_completed_reporting) · `academic_years` (11) · `nationalities` (15; `ZZZ` = home country placeholder) · `gender_categories` (4) · `delivery_modes` (2) · `attendance_loads` (2) · `academic_standing_codes` (5) · `student_status_codes` (7) · `schools` (5) · `programmes` (11 UG, 9 Master's, 4 Doctorate; `display_name` ends in "[synthetic placeholder]", `is_placeholder = True`) · `courses` (654) · `grading_schemes` (demonstration 4-point scale, labelled "Demo GPA (placeholder scale)") · `rule_sets` · `level_rules` (durations, windows, minimum years, credits, pass marks, GPA minimums) · `fee_schedules` · `roles` (9, for role-based access) · `servers` (10).
Every row carries `data_source`, `verification_status`, `source_reference`, `verified_on`, `verified_by`, and (like every synthetic row) `source_system` and `generation_run_id`.

## 5. Zone A UCI tables (implemented)
`uci_source_records` (all 37 original values, renamed) · `uci_students` (decoded labels; outcome_at_normal_duration; dq_flags incl. 180 × `NOT_EVALUATED_BOTH_SEMESTERS`) · `uci_semester_results` (2 per student: units, `uci_grade_raw`, `uci_mean_grade_passed_units_0_20` [never called GPA], pass_rate, evaluation_status, dq_flags) · `uci_course_categories` · `code_lookups`. Parent occupation and qualification codes are kept as raw codes (no labels loaded).

---

## 6. Calculation logic (`data_warehouse/pipelines/metrics.py`)

**Term reporting status** (relative to the as-of date 2026-11-10): `COMPLETED_TERM` (end ≤ as-of: grades, GPA, standing, graduations reportable) · `CENSUS_SNAPSHOT_ONLY` (census passed, term running: Fall 2026 headcount and retention only) · `FUTURE_NOT_REPORTABLE` (Spring/Summer 2027).

**Status at a term's census date:** `ENROLLED` (any programme) → `COMPLETED` (graduated, not enrolled) → `ON_GAP` (admission still open: stopped out) → `LEFT`. If a student fits more than one, the first applies.

| Metric | Definition |
|---|---|
| Enrolment | Headcount per term × level × school × programme × delivery mode × attendance load × gender × residency × nationality; unduplicated headcount per academic year. Fall 2026 is labelled CENSUS_SNAPSHOT_ONLY |
| Performance | Completed terms only. Semester GPA and cumulative GPA (credit-weighted, from final course grades, W excluded); standing counts (good / warning / probation / dismissed / not evaluated); poor performance (term GPA below level minimum or < 50 % of graded credits passed) by term, level, school, programme |
| Retention | `retention_cohort_members` → `retention_rates`. FIRST_YEAR_COHORT = INSTITUTIONAL cohort (first ever admission) measured at the same season one year later (Fall 2025 → Fall 2026); FALL_TO_FALL / SPRING_TO_SPRING / SUMMER_TO_SUMMER = everyone enrolled at the base census. **Institutional retention** = enrolled in any programme (transfers retained); **programme retention** = same programme. Graduates (COMPLETED) are never retained: reported as completions and removed from the denominator, `rate = retained / (cohort − completed)`; the unadjusted rate is also published. Groups: level, school, programme, delivery mode, load. Optional Summer: a student not enrolled at a Summer comparison but enrolled the next Fall is `CONTINUING_SKIPPED_OPTIONAL_SUMMER` (not stopped out / left) and a `summer_continuation_rate` is published. Comparison final only if its census has passed (Fall 2026 = `FINAL_CENSUS_SNAPSHOT`); otherwise INCOMPLETE and no rate. Never derived from differences between headcount totals |
| Multi-year cohort retention | INSTITUTIONAL cohort measured k = 1, 2, 3 years later (same season) |
| Graduation | `graduation_records` → `graduation_rates`. LEVEL_ENTRY cohort; graduated within window = graduation date ≤ entry-term start + window (UG 6, Master's 4, Doctorate 6: project-configured reporting assumptions). **Same maturity rule for every level**: mature only when the window end is on/before the as-of date and every term ending in the window is completed. Rates by cohort, and for mature cohorts by level, programme and school |
| Time-to-degree | (graduation date − original admission date at the level) / 365.25, plus enrolled-term and gap-term counts (D8) |

## 7. Rules enforced and validated (`data_warehouse/pipelines/validation.py`)
Every check recomputes from base records with code written separately from the generator and `metrics.py`.
- **Schema:** every file (synthetic and UCI) has a documented schema (`pipelines/schema.py`, exported as `data/synthetic/schema/data_dictionary.csv`); exact column sets, required values present, dates/numbers/booleans parse, values inside allowed domains.
- **Identifiers and relationships:** unique keys on 42 tables; 70 foreign keys (plus generation-run links) including nationality, gender, school, academic year, delivery mode and attendance load; every row's `generation_run_id` resolves.
- **Consistency:** enrolment school/level = its programme's; academic year and sequence = calendar; delivery mode offered by the programme; residency consistent with nationality; demographics equal the applicant.
- **Data separation & labels:** `data_source`, `source_system`, `generation_run_id` correct on every row; placeholders labelled; no UCI IDs or rows in synthetic files and vice versa; UCI tables contain no dates, terms, programmes, schools, modes or GPA; raw-file SHA-256 unchanged.
- **Calendar:** term dates ordered and non-overlapping; `term_status` and `reporting_status` consistent with the as-of date; a future/in-progress term can never be marked completed; final grades only in completed terms.
- **Timeline:** no enrolment before admission; admitted application precedes every admission; no enrolment after an outcome; no overlapping admissions; no simultaneous enrolment; outcome fields present exactly when an outcome exists.
- **Transfers:** same level, different programme, entry in the next regular term, transferred credits ≤ credits earned.
- **Graduation:** term-end date of a completed term, never after the as-of date, credits, minimum duration, GPA, not dismissed.
- **Progression:** gap counts recompute; the configurable missed-term withdrawal rule recomputes for every withdrawn and active admission.
- **Status history:** events recompute from admissions and enrolments; admission event preserved.
- **GPA, standing, performance:** grade points, credits, semester and cumulative GPA, standing (with carry-forward), one standing row per completed term, poor-performance flag.
- **Finance:** charges only for real enrolments; holds, past-due balances and hold flags recompute; no registration during a hold; balances = charges − payments.
- **IT / Data Warehouse:** logins only on active accounts; accounts before first term; server status coherent; sync failures on outage days.
- **Retention:** membership complete; each member outcome and every rate recomputes (institutional, programme, completions excluded); groups add up; incomplete comparisons publish no rate; nothing final in 2027.
- **Graduation records and rates:** window, maturity (same rule for all levels), status, dates and time-to-degree recompute; UG/Master's/Doctorate final rates recompute; immature cohorts publish no rate.
- **Aggregates:** enrolment and performance outputs add up to the base records.
- **Reproducibility:** same seed gives byte-identical files; another seed gives different files; UCI unchanged.

The validator is itself tested: `tests/test_validator_mutations.py` plants 31 different errors (e.g. graduation after the as-of date, graduation before the minimum duration, invalid delivery mode, wrong school, tampered GPA, enrolment after graduation, missing required field, UCI row and UCI ID leaks, 2027 marked completed, graded in-progress term, graduate counted as retained, dropped retention member, tampered graduation status, changed Doctorate window, duplicate ID, broken foreign key, impossible date, invalid transfer, tampered balance, deleted hold, tampered standing, withdrawal-rule date) and asserts that the specific check fails.

## 8. Recorded decisions D1–D18
| # | Decision |
|---|---|
| D1 | data_source values: UCI, SYNTHETIC, EXTERNAL_REFERENCE |
| D2 | UCI kept separate. No invented admission dates, terms or graduation dates |
| D3 | UCI course categories separate from university programmes |
| D4–D5 | Verified schools and programmes when available. Placeholders flagged (all current ones are placeholders) |
| D6 | Fall/Spring/Summer terms. Summer admission allowed (configurable) |
| D7 | Durations configurable. Graduation windows UG 6, Master's 4, Doctorate 6 years are **project-configured reporting assumptions** requested for this dashboard (not verified policy); all three use the same maturity rule |
| D8 | Time-to-degree = elapsed calendar time. Enrolled-term count kept separately |
| D9 | UCI 0–20 grades preserved and never called GPA. Synthetic grading uses a separate configurable scheme |
| D10 | Warning, probation and dismissal thresholds configurable placeholders |
| D11 | Cohorts by first admission term, filterable by level and study mode |
| D12 | Retained = still enrolled. Graduates = completions. Programme changers = retained |
| D13 | Gaps allowed and recorded (`prior_gap_terms`) |
| D14 | Multiple programmes over time allowed |
| D15 | 180 zero-unit UCI records kept and flagged |
| D16 | Application types are not derived from UCI codes |
| D17 | Delivery mode recorded per term enrolment |
| D18 | Incomplete cohorts shown with an INCOMPLETE label, never as final |

## 9. Clarifications resolved during implementation
C1 windows ≠ normal durations · C2 two cohort types · C3/C4 admissions Fall 2016–Fall 2026, as-of 2026-11-10, 2027 = FUTURE · C5 Summer cohorts measured both ways · C6 readmission allowed · C7 Summer is not a gap; > 3 missed regular terms = withdrawal · C8 study-mode filters for both delivery mode and load · C9 four placeholder gender categories · C10 no concurrent enrolment. Details are in `README.md` §6 and `data_warehouse/config/synthetic_config.toml`.

## 10. Still requires verified university information
| # | Information | Replaces placeholder in |
|---|---|---|
| V1 | University name and official source documents | all Zone C tables |
| V2 | Schools/faculties | `schools` |
| V3 | Programmes (name, level, school, delivery modes, credits) and course catalogue | `programmes`, `courses` |
| V4 | Academic calendar dates; Summer as a full and admitting term | `academic_terms` |
| V5 | Normal programme durations | `level_rules` |
| V6 | Official graduation-rate windows (current UG 6 / Master's 4 / Doctorate 6 are project-configured assumptions) | `level_rules` |
| V7 | Minimum time to graduate | `level_rules` |
| V8 | Grading scale, pass marks, whether it is officially "GPA", repeat-course policy | `grading_schemes`, `level_rules` |
| V9 | Warning, probation and dismissal policy, and the route back to good standing | `rule_sets` |
| V10 | Census date definition | `academic_terms` |
| V11 | Leave-of-absence / maximum-gap policy (replaces synthetic rule `SYN-WD-MISSED-TERMS`, > 3 missed regular terms) | `rule_sets`, `academic.max_consecutive_missed_terms` |
| V12 | Graduation date definition (conferral vs term end) | `rule_sets` |
| V13 | Official retention/graduation reporting standard | `metrics.py` |
| V14 | Fee schedule, currency, hold and refund policy | `fee_schedules`, finance config |
| V15 | Staff roles and access policy (for RBAC) | `roles` |
| V16 | Home country (replaces `ZZZ`) and the university's gender categories | demographics config |

## 11. Revision 4 change log (generator 1.1.0)
| Area | Change |
|---|---|
| Graduation windows | Doctorate 6-year window relabelled `PROJECT_CONFIGURED_REPORTING_ASSUMPTION` (as are UG 6 and Master's 4); same maturity rule for all levels |
| Fall 2026 | `reporting_status = CENSUS_SNAPSHOT_ONLY`: headcount and census retention only; no grades, standing, flags or graduations. 2027 terms `FUTURE_NOT_REPORTABLE` |
| Withdrawal rule | Documented as configurable synthetic business rule `SYN-WD-MISSED-TERMS` (config, `rule_sets`, status history). Simulator bug fixed: the limit is now checked on every missed-term path (2 withdrawals were previously recorded one term late) |
| Standing | One row per completed term (728 previously missing rows for all-withdrawn terms now carry the standing forward) |
| New fields | `term_enrolments.school_id / academic_year / passed_credit_ratio / poor_performance_flag`; `applications.school_id`; `display_name`, `is_placeholder`; `source_system`, `generation_run_id` everywhere |
| New tables | 7 reference code tables; `student_status_history`; `retention_cohort_members`; `graduation_records`; `generation_runs`; `schema/data_dictionary.csv` |
| Final audit | Stale 1.0.0 metric files moved to `reports/superseded_generator_1.0.0/`; optional-Summer classification corrected (`CONTINUING_SKIPPED_OPTIONAL_SUMMER`). See `data/synthetic/reports/final_dataset_audit.md` |
