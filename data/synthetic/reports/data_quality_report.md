# Data Quality Report: institutional analytics dataset

> **Synthetic institutional records are DEMONSTRATION DATA, NOT REAL UNIVERSITY RECORDS.** UCI records are real public data kept in a separate zone. The two populations are never combined.

- Generation run `SYN-RUN-1.1.0-S20261110` · generator `1.1.0` · seed `20261110` · as-of date `2026-11-10`
- Validation: **473 checks passed, 0 failed** (40 s)

## 1. UCI coverage (Zone A, real public data)

- Source: `data/raw/data.csv` (UCI *Predict Students' Dropout and Academic Success*), SHA-256 `3ef126de5cefff26...` verified unchanged.
- Processed tables: `code_lookups` (79 rows), `uci_course_categories` (17 rows), `uci_semester_results` (8,848 rows), `uci_source_records` (4,424 rows), `uci_students` (4,424 rows)
- 4,424 students; outcomes at normal duration: GRADUATED 2,209, DROPPED_OUT 1,421, STILL_ENROLLED 794
- Covers: demographics, nationality, application mode/order, previous qualification, admission grade, first-year semester units and 0-20 grades (not GPA), scholarship/debtor/fees flags, macro-economic context, outcome at normal duration.
- Not covered (never invented): calendar terms, admission/graduation dates, schools, university programmes, delivery mode, official GPA, multi-year enrolment, retention terms.

## 2. Existing synthetic coverage (before this revision, generator 1.0.0)

- 5,000 synthetic students 2016FA-2026FA: admissions/applications, programme admissions, term and course enrolments, grades, GPA, standing, cohorts, charges/payments/holds, IT accounts/logins/servers, data-warehouse sync log.
- Retention/graduation were computed only in report outputs (no member-level records).

## 3. Missing features found by the audit

| Gap | Impact |
|---|---|
| `school_id`, `academic_year` missing on term enrolments | enrolment by school / academic year needed joins |
| no reference tables for academic years, nationalities, genders, delivery modes, attendance loads, status codes | unvalidated codes |
| 728 completed term enrolments (all courses withdrawn) had no standing row | incomplete standing history |
| no poor-performance flag | performance module incomplete |
| no student status history | stop-out / return / withdrawal events not traceable |
| no retention cohort membership, no programme retention, graduates not removed from the denominator | retention not auditable |
| no graduation records (eligibility, maturity, status per student) | graduation module not auditable |
| Doctorate window labelled UNCONFIRMED; withdrawal rule not documented as a business rule | labelling |
| no generation-run id / source system on rows; no documented schema or data dictionary | lineage |

## 4. Features generated or corrected (generator 1.1.0)

- **Corrected**: Doctorate 6-year window relabelled *project-configured reporting assumption* (same maturity rule as UG/Master's); term `reporting_status` (COMPLETED_TERM / CENSUS_SNAPSHOT_ONLY / FUTURE_NOT_REPORTABLE); missed-term withdrawal documented as configurable synthetic rule `SYN-WD-MISSED-TERMS`; standing written for every completed term (carried forward when ungraded).
- **Added fields**: `term_enrolments.school_id`, `academic_year`, `passed_credit_ratio`, `poor_performance_flag`; `applications.school_id`; `display_name` / `is_placeholder` on schools and programmes; `source_system` + `generation_run_id` on every synthetic row.
- **Added tables**: `reference/academic_years`, `nationalities`, `gender_categories`, `delivery_modes`, `attendance_loads`, `academic_standing_codes`, `student_status_codes`; `registrar/student_status_history`, `retention_cohort_members`, `graduation_records`; `data_warehouse/generation_runs`; `schema/data_dictionary.csv`.
- **Metric outputs** (`reports/metrics/`): retention_rates, cohort_retention_multi_year, graduation_rates, time_to_degree, enrolment_by_term, enrolment_by_academic_year, performance_by_term.

## 5. Final record counts

| File | Rows |
|---|---:|
| `admissions/applicants` | 13,320 |
| `admissions/applications` | 13,600 |
| `data_warehouse/generation_runs` | 1 |
| `data_warehouse/sync_runs` | 720 |
| `finance/account_balances` | 5,000 |
| `finance/charges` | 116,157 |
| `finance/financial_holds` | 4,111 |
| `finance/payments` | 60,239 |
| `finance/registration_blocks` | 609 |
| `it/account_status_events` | 8,315 |
| `it/incidents` | 76 |
| `it/login_events` | 134,387 |
| `it/server_status_daily` | 1,800 |
| `it/staff` | 140 |
| `it/user_accounts` | 5,140 |
| `reference/academic_standing_codes` | 5 |
| `reference/academic_terms` | 33 |
| `reference/academic_years` | 11 |
| `reference/attendance_loads` | 2 |
| `reference/courses` | 654 |
| `reference/delivery_modes` | 2 |
| `reference/fee_schedules` | 33 |
| `reference/gender_categories` | 4 |
| `reference/grading_schemes` | 1 |
| `reference/level_rules` | 3 |
| `reference/nationalities` | 15 |
| `reference/programmes` | 24 |
| `reference/roles` | 9 |
| `reference/rule_sets` | 1 |
| `reference/schools` | 5 |
| `reference/servers` | 10 |
| `reference/student_status_codes` | 7 |
| `registrar/academic_standing` | 29,856 |
| `registrar/cohort_members` | 10,154 |
| `registrar/cohorts` | 124 |
| `registrar/course_enrolments` | 112,408 |
| `registrar/graduation_records` | 5,154 |
| `registrar/retention_cohort_members` | 36,965 |
| `registrar/student_programmes` | 5,556 |
| `registrar/student_status_history` | 11,007 |
| `registrar/students` | 5,000 |
| `registrar/term_enrolments` | 31,965 |

## 6. Checks passed and failed

| Category | Checks | Failed |
|---|---:|---:|
| Schema | 128 | 0 |
| Schema (UCI) | 15 | 0 |
| Identifiers | 43 | 0 |
| Relationships | 71 | 0 |
| Consistency | 16 | 0 |
| Data separation | 69 | 0 |
| Source labels | 44 | 0 |
| Calendar | 5 | 0 |
| Future terms | 6 | 0 |
| Timeline | 14 | 0 |
| Transfers | 1 | 0 |
| Graduation | 8 | 0 |
| Progression | 3 | 0 |
| Status history | 1 | 0 |
| GPA & standing | 8 | 0 |
| Cohorts | 5 | 0 |
| Finance | 12 | 0 |
| IT | 5 | 0 |
| Data warehouse | 1 | 0 |
| Retention | 12 | 0 |
| Enrolment | 3 | 0 |
| Performance | 3 | 0 |

<details><summary>All checks</summary>

| Category | Check | Result | Detail |
|---|---|---|---|
| Schema | reference/academic_terms: required fields present | PASS | 33 rows |
| Schema | reference/academic_terms: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/academic_terms: values within allowed domains | PASS |  |
| Schema | reference/academic_years: required fields present | PASS | 11 rows |
| Schema | reference/academic_years: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/academic_years: values within allowed domains | PASS |  |
| Schema | reference/schools: required fields present | PASS | 5 rows |
| Schema | reference/schools: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/schools: values within allowed domains | PASS |  |
| Schema | reference/programmes: required fields present | PASS | 24 rows |
| Schema | reference/programmes: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/programmes: values within allowed domains | PASS |  |
| Schema | reference/courses: required fields present | PASS | 654 rows |
| Schema | reference/courses: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/courses: values within allowed domains | PASS |  |
| Schema | reference/grading_schemes: required fields present | PASS | 1 rows |
| Schema | reference/grading_schemes: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/grading_schemes: values within allowed domains | PASS |  |
| Schema | reference/rule_sets: required fields present | PASS | 1 rows |
| Schema | reference/rule_sets: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/rule_sets: values within allowed domains | PASS |  |
| Schema | reference/level_rules: required fields present | PASS | 3 rows |
| Schema | reference/level_rules: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/level_rules: values within allowed domains | PASS |  |
| Schema | reference/fee_schedules: required fields present | PASS | 33 rows |
| Schema | reference/fee_schedules: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/fee_schedules: values within allowed domains | PASS |  |
| Schema | reference/nationalities: required fields present | PASS | 15 rows |
| Schema | reference/nationalities: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/nationalities: values within allowed domains | PASS |  |
| Schema | reference/gender_categories: required fields present | PASS | 4 rows |
| Schema | reference/gender_categories: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/gender_categories: values within allowed domains | PASS |  |
| Schema | reference/delivery_modes: required fields present | PASS | 2 rows |
| Schema | reference/delivery_modes: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/delivery_modes: values within allowed domains | PASS |  |
| Schema | reference/attendance_loads: required fields present | PASS | 2 rows |
| Schema | reference/attendance_loads: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/attendance_loads: values within allowed domains | PASS |  |
| Schema | reference/academic_standing_codes: required fields present | PASS | 5 rows |
| Schema | reference/academic_standing_codes: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/academic_standing_codes: values within allowed domains | PASS |  |
| Schema | reference/student_status_codes: required fields present | PASS | 7 rows |
| Schema | reference/student_status_codes: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/student_status_codes: values within allowed domains | PASS |  |
| Schema | reference/roles: required fields present | PASS | 9 rows |
| Schema | reference/roles: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/roles: values within allowed domains | PASS |  |
| Schema | reference/servers: required fields present | PASS | 10 rows |
| Schema | reference/servers: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | reference/servers: values within allowed domains | PASS |  |
| Schema | admissions/applicants: required fields present | PASS | 13320 rows |
| Schema | admissions/applicants: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | admissions/applicants: values within allowed domains | PASS |  |
| Schema | admissions/applications: required fields present | PASS | 13600 rows |
| Schema | admissions/applications: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | admissions/applications: values within allowed domains | PASS |  |
| Schema | registrar/students: required fields present | PASS | 5000 rows |
| Schema | registrar/students: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/students: values within allowed domains | PASS |  |
| Schema | registrar/student_programmes: required fields present | PASS | 5556 rows |
| Schema | registrar/student_programmes: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/student_programmes: values within allowed domains | PASS |  |
| Schema | registrar/term_enrolments: required fields present | PASS | 31965 rows |
| Schema | registrar/term_enrolments: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/term_enrolments: values within allowed domains | PASS |  |
| Schema | registrar/course_enrolments: required fields present | PASS | 112408 rows |
| Schema | registrar/course_enrolments: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/course_enrolments: values within allowed domains | PASS |  |
| Schema | registrar/academic_standing: required fields present | PASS | 29856 rows |
| Schema | registrar/academic_standing: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/academic_standing: values within allowed domains | PASS |  |
| Schema | registrar/cohorts: required fields present | PASS | 124 rows |
| Schema | registrar/cohorts: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/cohorts: values within allowed domains | PASS |  |
| Schema | registrar/cohort_members: required fields present | PASS | 10154 rows |
| Schema | registrar/cohort_members: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/cohort_members: values within allowed domains | PASS |  |
| Schema | registrar/student_status_history: required fields present | PASS | 11007 rows |
| Schema | registrar/student_status_history: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/student_status_history: values within allowed domains | PASS |  |
| Schema | registrar/retention_cohort_members: required fields present | PASS | 36965 rows |
| Schema | registrar/retention_cohort_members: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/retention_cohort_members: values within allowed domains | PASS |  |
| Schema | registrar/graduation_records: required fields present | PASS | 5154 rows |
| Schema | registrar/graduation_records: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | registrar/graduation_records: values within allowed domains | PASS |  |
| Schema | finance/charges: required fields present | PASS | 116157 rows |
| Schema | finance/charges: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | finance/charges: values within allowed domains | PASS |  |
| Schema | finance/payments: required fields present | PASS | 60239 rows |
| Schema | finance/payments: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | finance/payments: values within allowed domains | PASS |  |
| Schema | finance/financial_holds: required fields present | PASS | 4111 rows |
| Schema | finance/financial_holds: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | finance/financial_holds: values within allowed domains | PASS |  |
| Schema | finance/registration_blocks: required fields present | PASS | 609 rows |
| Schema | finance/registration_blocks: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | finance/registration_blocks: values within allowed domains | PASS |  |
| Schema | finance/account_balances: required fields present | PASS | 5000 rows |
| Schema | finance/account_balances: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | finance/account_balances: values within allowed domains | PASS |  |
| Schema | it/user_accounts: required fields present | PASS | 5140 rows |
| Schema | it/user_accounts: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | it/user_accounts: values within allowed domains | PASS |  |
| Schema | it/account_status_events: required fields present | PASS | 8315 rows |
| Schema | it/account_status_events: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | it/account_status_events: values within allowed domains | PASS |  |
| Schema | it/staff: required fields present | PASS | 140 rows |
| Schema | it/staff: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | it/staff: values within allowed domains | PASS |  |
| Schema | it/login_events: required fields present | PASS | 134387 rows |
| Schema | it/login_events: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | it/login_events: values within allowed domains | PASS |  |
| Schema | it/server_status_daily: required fields present | PASS | 1800 rows |
| Schema | it/server_status_daily: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | it/server_status_daily: values within allowed domains | PASS |  |
| Schema | it/incidents: required fields present | PASS | 76 rows |
| Schema | it/incidents: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | it/incidents: values within allowed domains | PASS |  |
| Schema | data_warehouse/sync_runs: required fields present | PASS | 720 rows |
| Schema | data_warehouse/sync_runs: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | data_warehouse/sync_runs: values within allowed domains | PASS |  |
| Schema | data_warehouse/generation_runs: required fields present | PASS | 1 rows |
| Schema | data_warehouse/generation_runs: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema | data_warehouse/generation_runs: values within allowed domains | PASS |  |
| Schema | every synthetic file has a documented schema | PASS | 42 files |
| Schema (UCI) | uci/uci_students: required fields present | PASS | 4424 rows |
| Schema (UCI) | uci/uci_students: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema (UCI) | uci/uci_students: values within allowed domains | PASS |  |
| Schema (UCI) | uci/uci_semester_results: required fields present | PASS | 8848 rows |
| Schema (UCI) | uci/uci_semester_results: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema (UCI) | uci/uci_semester_results: values within allowed domains | PASS |  |
| Schema (UCI) | uci/uci_course_categories: required fields present | PASS | 17 rows |
| Schema (UCI) | uci/uci_course_categories: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema (UCI) | uci/uci_course_categories: values within allowed domains | PASS |  |
| Schema (UCI) | uci/code_lookups: required fields present | PASS | 79 rows |
| Schema (UCI) | uci/code_lookups: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema (UCI) | uci/code_lookups: values within allowed domains | PASS |  |
| Schema (UCI) | uci/uci_source_records: required fields present | PASS | 4424 rows |
| Schema (UCI) | uci/uci_source_records: values parse as documented types (dates, numbers, booleans) | PASS |  |
| Schema (UCI) | uci/uci_source_records: values within allowed domains | PASS |  |
| Schema | every UCI file has a documented schema | PASS | [] |
| Identifiers | admissions/applicants.applicant_id unique and not null | PASS | 13320 rows |
| Identifiers | admissions/applications.application_id unique and not null | PASS | 13600 rows |
| Identifiers | registrar/students.student_id unique and not null | PASS | 5000 rows |
| Identifiers | registrar/student_programmes.student_programme_id unique and not null | PASS | 5556 rows |
| Identifiers | registrar/term_enrolments.term_enrolment_id unique and not null | PASS | 31965 rows |
| Identifiers | registrar/course_enrolments.course_enrolment_id unique and not null | PASS | 112408 rows |
| Identifiers | registrar/academic_standing.standing_id unique and not null | PASS | 29856 rows |
| Identifiers | registrar/cohorts.cohort_id unique and not null | PASS | 124 rows |
| Identifiers | registrar/cohort_members.cohort_id+student_id unique and not null | PASS | 10154 rows |
| Identifiers | registrar/student_status_history.status_event_id unique and not null | PASS | 11007 rows |
| Identifiers | registrar/retention_cohort_members.retention_record_id unique and not null | PASS | 36965 rows |
| Identifiers | registrar/graduation_records.graduation_record_id unique and not null | PASS | 5154 rows |
| Identifiers | finance/charges.charge_id unique and not null | PASS | 116157 rows |
| Identifiers | finance/payments.payment_id unique and not null | PASS | 60239 rows |
| Identifiers | finance/financial_holds.hold_id unique and not null | PASS | 4111 rows |
| Identifiers | finance/registration_blocks.block_id unique and not null | PASS | 609 rows |
| Identifiers | finance/account_balances.student_id unique and not null | PASS | 5000 rows |
| Identifiers | it/user_accounts.account_id unique and not null | PASS | 5140 rows |
| Identifiers | it/account_status_events.event_id unique and not null | PASS | 8315 rows |
| Identifiers | it/staff.staff_id unique and not null | PASS | 140 rows |
| Identifiers | it/login_events.login_id unique and not null | PASS | 134387 rows |
| Identifiers | it/incidents.incident_id unique and not null | PASS | 76 rows |
| Identifiers | it/server_status_daily.server_id+status_date unique and not null | PASS | 1800 rows |
| Identifiers | data_warehouse/sync_runs.run_id unique and not null | PASS | 720 rows |
| Identifiers | data_warehouse/generation_runs.generation_run_id unique and not null | PASS | 1 rows |
| Identifiers | reference/programmes.programme_id unique and not null | PASS | 24 rows |
| Identifiers | reference/courses.course_id unique and not null | PASS | 654 rows |
| Identifiers | reference/academic_terms.term_id unique and not null | PASS | 33 rows |
| Identifiers | reference/academic_years.academic_year unique and not null | PASS | 11 rows |
| Identifiers | reference/schools.school_id unique and not null | PASS | 5 rows |
| Identifiers | reference/nationalities.nationality_iso3 unique and not null | PASS | 15 rows |
| Identifiers | reference/gender_categories.gender unique and not null | PASS | 4 rows |
| Identifiers | reference/delivery_modes.delivery_mode unique and not null | PASS | 2 rows |
| Identifiers | reference/attendance_loads.study_load unique and not null | PASS | 2 rows |
| Identifiers | reference/academic_standing_codes.standing unique and not null | PASS | 5 rows |
| Identifiers | reference/student_status_codes.status_code unique and not null | PASS | 7 rows |
| Identifiers | reference/level_rules.level unique and not null | PASS | 3 rows |
| Identifiers | reference/fee_schedules.academic_year+level unique and not null | PASS | 33 rows |
| Identifiers | reference/roles.role_code unique and not null | PASS | 9 rows |
| Identifiers | reference/servers.server_id unique and not null | PASS | 10 rows |
| Identifiers | reference/grading_schemes.grading_scheme_id unique and not null | PASS | 1 rows |
| Identifiers | reference/rule_sets.rule_set_id unique and not null | PASS | 1 rows |
| Identifiers | student_id format SYN-nnnnnn | PASS |  |
| Relationships | admissions/applications.applicant_id -> admissions/applicants.applicant_id | PASS | 13600 non-null links |
| Relationships | admissions/applications.student_id -> registrar/students.student_id | PASS | 5280 non-null links |
| Relationships | admissions/applications.programme_id -> reference/programmes.programme_id | PASS | 13600 non-null links |
| Relationships | admissions/applications.school_id -> reference/schools.school_id | PASS | 13600 non-null links |
| Relationships | admissions/applications.entry_term_id -> reference/academic_terms.term_id | PASS | 13600 non-null links |
| Relationships | admissions/applicants.nationality_iso3 -> reference/nationalities.nationality_iso3 | PASS | 13320 non-null links |
| Relationships | admissions/applicants.gender -> reference/gender_categories.gender | PASS | 13320 non-null links |
| Relationships | registrar/students.applicant_id -> admissions/applicants.applicant_id | PASS | 5000 non-null links |
| Relationships | registrar/students.nationality_iso3 -> reference/nationalities.nationality_iso3 | PASS | 5000 non-null links |
| Relationships | registrar/students.gender -> reference/gender_categories.gender | PASS | 5000 non-null links |
| Relationships | registrar/student_programmes.student_id -> registrar/students.student_id | PASS | 5556 non-null links |
| Relationships | registrar/student_programmes.programme_id -> reference/programmes.programme_id | PASS | 5556 non-null links |
| Relationships | registrar/student_programmes.school_id -> reference/schools.school_id | PASS | 5556 non-null links |
| Relationships | registrar/student_programmes.entry_term_id -> reference/academic_terms.term_id | PASS | 5556 non-null links |
| Relationships | registrar/student_programmes.outcome_term_id -> reference/academic_terms.term_id | PASS | 3287 non-null links |
| Relationships | registrar/student_programmes.previous_student_programme_id -> registrar/student_programmes.student_programme_id | PASS | 556 non-null links |
| Relationships | registrar/student_programmes.application_id -> admissions/applications.application_id | PASS | 5280 non-null links |
| Relationships | registrar/student_programmes.rule_set_id -> reference/rule_sets.rule_set_id | PASS | 5556 non-null links |
| Relationships | registrar/term_enrolments.student_programme_id -> registrar/student_programmes.student_programme_id | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.student_id -> registrar/students.student_id | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.programme_id -> reference/programmes.programme_id | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.school_id -> reference/schools.school_id | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.term_id -> reference/academic_terms.term_id | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.academic_year -> reference/academic_years.academic_year | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.delivery_mode -> reference/delivery_modes.delivery_mode | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.study_load -> reference/attendance_loads.study_load | PASS | 31965 non-null links |
| Relationships | registrar/term_enrolments.grading_scheme_id -> reference/grading_schemes.grading_scheme_id | PASS | 31965 non-null links |
| Relationships | registrar/course_enrolments.term_enrolment_id -> registrar/term_enrolments.term_enrolment_id | PASS | 112408 non-null links |
| Relationships | registrar/course_enrolments.course_id -> reference/courses.course_id | PASS | 112408 non-null links |
| Relationships | registrar/course_enrolments.delivery_mode -> reference/delivery_modes.delivery_mode | PASS | 112408 non-null links |
| Relationships | registrar/academic_standing.term_enrolment_id -> registrar/term_enrolments.term_enrolment_id | PASS | 29856 non-null links |
| Relationships | registrar/academic_standing.standing -> reference/academic_standing_codes.standing | PASS | 29856 non-null links |
| Relationships | registrar/cohort_members.cohort_id -> registrar/cohorts.cohort_id | PASS | 10154 non-null links |
| Relationships | registrar/cohort_members.student_programme_id -> registrar/student_programmes.student_programme_id | PASS | 10154 non-null links |
| Relationships | registrar/cohort_members.programme_at_entry -> reference/programmes.programme_id | PASS | 10154 non-null links |
| Relationships | registrar/student_status_history.student_programme_id -> registrar/student_programmes.student_programme_id | PASS | 11007 non-null links |
| Relationships | registrar/student_status_history.term_id -> reference/academic_terms.term_id | PASS | 11007 non-null links |
| Relationships | registrar/student_status_history.status_code -> reference/student_status_codes.status_code | PASS | 11007 non-null links |
| Relationships | registrar/retention_cohort_members.student_id -> registrar/students.student_id | PASS | 36965 non-null links |
| Relationships | registrar/retention_cohort_members.base_programme_id -> reference/programmes.programme_id | PASS | 36965 non-null links |
| Relationships | registrar/retention_cohort_members.base_school_id -> reference/schools.school_id | PASS | 36965 non-null links |
| Relationships | registrar/retention_cohort_members.base_term_id -> reference/academic_terms.term_id | PASS | 36965 non-null links |
| Relationships | registrar/retention_cohort_members.compare_term_id -> reference/academic_terms.term_id | PASS | 34468 non-null links |
| Relationships | registrar/retention_cohort_members.compare_programme_id -> reference/programmes.programme_id | PASS | 22736 non-null links |
| Relationships | registrar/graduation_records.cohort_id -> registrar/cohorts.cohort_id | PASS | 5154 non-null links |
| Relationships | registrar/graduation_records.student_id -> registrar/students.student_id | PASS | 5154 non-null links |
| Relationships | registrar/graduation_records.programme_at_entry -> reference/programmes.programme_id | PASS | 5154 non-null links |
| Relationships | registrar/graduation_records.school_at_entry -> reference/schools.school_id | PASS | 5154 non-null links |
| Relationships | registrar/graduation_records.graduated_programme_id -> reference/programmes.programme_id | PASS | 1821 non-null links |
| Relationships | registrar/graduation_records.graduation_term_id -> reference/academic_terms.term_id | PASS | 1821 non-null links |
| Relationships | reference/programmes.school_id -> reference/schools.school_id | PASS | 24 non-null links |
| Relationships | reference/courses.programme_id -> reference/programmes.programme_id | PASS | 654 non-null links |
| Relationships | reference/fee_schedules.academic_year -> reference/academic_years.academic_year | PASS | 33 non-null links |
| Relationships | reference/academic_terms.academic_year -> reference/academic_years.academic_year | PASS | 33 non-null links |
| Relationships | finance/charges.student_id -> registrar/students.student_id | PASS | 116157 non-null links |
| Relationships | finance/charges.student_programme_id -> registrar/student_programmes.student_programme_id | PASS | 116157 non-null links |
| Relationships | finance/charges.term_id -> reference/academic_terms.term_id | PASS | 116157 non-null links |
| Relationships | finance/payments.student_id -> registrar/students.student_id | PASS | 60239 non-null links |
| Relationships | finance/payments.term_id -> reference/academic_terms.term_id | PASS | 59399 non-null links |
| Relationships | finance/financial_holds.student_id -> registrar/students.student_id | PASS | 4111 non-null links |
| Relationships | finance/registration_blocks.student_programme_id -> registrar/student_programmes.student_programme_id | PASS | 609 non-null links |
| Relationships | finance/registration_blocks.term_id -> reference/academic_terms.term_id | PASS | 609 non-null links |
| Relationships | finance/account_balances.student_id -> registrar/students.student_id | PASS | 5000 non-null links |
| Relationships | it/user_accounts.role_code -> reference/roles.role_code | PASS | 5140 non-null links |
| Relationships | it/staff.role_code -> reference/roles.role_code | PASS | 140 non-null links |
| Relationships | it/login_events.account_id -> it/user_accounts.account_id | PASS | 134387 non-null links |
| Relationships | it/login_events.server_id -> reference/servers.server_id | PASS | 134387 non-null links |
| Relationships | it/account_status_events.account_id -> it/user_accounts.account_id | PASS | 8315 non-null links |
| Relationships | it/server_status_daily.server_id -> reference/servers.server_id | PASS | 1800 non-null links |
| Relationships | it/incidents.server_id -> reference/servers.server_id | PASS | 76 non-null links |
| Relationships | every row's generation_run_id -> data_warehouse/generation_runs | PASS | ['SYN-RUN-1.1.0-S20261110'] |
| Consistency | term enrolment student/programme/level equal its admission record | PASS |  |
| Consistency | term_enrolments: school = school of its programme | PASS |  |
| Consistency | student_programmes: school = school of its programme | PASS |  |
| Consistency | applications: school = school of its programme | PASS |  |
| Consistency | retention_cohort_members: school = school of its programme | PASS |  |
| Consistency | graduation_records: school = school of its programme | PASS |  |
| Consistency | term_enrolments: level = level of its programme | PASS |  |
| Consistency | student_programmes: level = level of its programme | PASS |  |
| Consistency | applications: level = level of its programme | PASS |  |
| Consistency | term enrolment academic year and sequence equal the calendar | PASS |  |
| Consistency | delivery mode of every term enrolment is offered by its programme | PASS |  |
| Consistency | course enrolments use their term's delivery mode and their programme's courses | PASS |  |
| Consistency | registrar/students: residency status consistent with nationality | PASS |  |
| Consistency | admissions/applicants: residency status consistent with nationality | PASS |  |
| Consistency | student demographics equal their applicant record | PASS |  |
| Consistency | graduation records belong to LEVEL_ENTRY cohort members with the same entry programme | PASS |  |
| Data separation | admissions/applicants: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | admissions/applicants: source_system = ADMISSIONS | PASS | ['ADMISSIONS'] |
| Data separation | admissions/applications: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | admissions/applications: source_system = ADMISSIONS | PASS | ['ADMISSIONS'] |
| Data separation | data_warehouse/generation_runs: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | data_warehouse/generation_runs: source_system = DATA_WAREHOUSE | PASS | ['DATA_WAREHOUSE'] |
| Data separation | data_warehouse/sync_runs: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | data_warehouse/sync_runs: source_system = DATA_WAREHOUSE | PASS | ['DATA_WAREHOUSE'] |
| Data separation | finance/account_balances: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | finance/account_balances: source_system = FINANCE | PASS | ['FINANCE'] |
| Data separation | finance/charges: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | finance/charges: source_system = FINANCE | PASS | ['FINANCE'] |
| Data separation | finance/financial_holds: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | finance/financial_holds: source_system = FINANCE | PASS | ['FINANCE'] |
| Data separation | finance/payments: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | finance/payments: source_system = FINANCE | PASS | ['FINANCE'] |
| Data separation | finance/registration_blocks: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | finance/registration_blocks: source_system = FINANCE | PASS | ['FINANCE'] |
| Data separation | it/account_status_events: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | it/account_status_events: source_system = IT | PASS | ['IT'] |
| Data separation | it/incidents: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | it/incidents: source_system = IT | PASS | ['IT'] |
| Data separation | it/login_events: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | it/login_events: source_system = IT | PASS | ['IT'] |
| Data separation | it/server_status_daily: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | it/server_status_daily: source_system = IT | PASS | ['IT'] |
| Data separation | it/staff: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | it/staff: source_system = IT | PASS | ['IT'] |
| Data separation | it/user_accounts: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | it/user_accounts: source_system = IT | PASS | ['IT'] |
| Data separation | reference/academic_standing_codes: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/academic_standing_codes: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/academic_standing_codes: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/academic_terms: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/academic_terms: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/academic_terms: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/academic_years: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/academic_years: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/academic_years: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/attendance_loads: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/attendance_loads: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/attendance_loads: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/courses: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/courses: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/courses: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/delivery_modes: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/delivery_modes: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/delivery_modes: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/fee_schedules: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/fee_schedules: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/fee_schedules: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/gender_categories: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/gender_categories: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/gender_categories: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/grading_schemes: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/grading_schemes: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/grading_schemes: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/level_rules: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/level_rules: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/level_rules: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/nationalities: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/nationalities: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/nationalities: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/programmes: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/programmes: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/programmes: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/roles: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/roles: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/roles: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/rule_sets: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/rule_sets: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/rule_sets: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/schools: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/schools: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/schools: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/servers: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/servers: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/servers: verification_status = PLACEHOLDER | PASS |  |
| Data separation | reference/student_status_codes: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | reference/student_status_codes: source_system = REFERENCE_PLACEHOLDER | PASS | ['REFERENCE_PLACEHOLDER'] |
| Data separation | reference/student_status_codes: verification_status = PLACEHOLDER | PASS |  |
| Data separation | registrar/academic_standing: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/academic_standing: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/cohort_members: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/cohort_members: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/cohorts: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/cohorts: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/course_enrolments: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/course_enrolments: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/graduation_records: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/graduation_records: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/retention_cohort_members: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/retention_cohort_members: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/student_programmes: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/student_programmes: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/student_status_history: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/student_status_history: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/students: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/students: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Data separation | registrar/term_enrolments: data_source = SYNTHETIC | PASS | ['SYNTHETIC'] |
| Source labels | registrar/term_enrolments: source_system = REGISTRAR | PASS | ['REGISTRAR'] |
| Source labels | generation_run_id on every row equals the manifest run | PASS | SYN-RUN-1.1.0-S20261110 |
| Source labels | generation run records version, seed and config fingerprint of the manifest | PASS |  |
| Data separation | reference/schools: labelled as synthetic placeholders (not verified names) | PASS |  |
| Data separation | reference/programmes: labelled as synthetic placeholders (not verified names) | PASS |  |
| Data separation | no UCI identifiers inside synthetic files | PASS |  |
| Data separation | original UCI file unchanged (SHA-256) | PASS |  |
| Data separation | UCI students: 4,424 rows, data_source = UCI | PASS |  |
| Data separation | UCI outcome counts 2209/1421/794 preserved | PASS |  |
| Data separation | 180 UCI records flagged NOT_EVALUATED_BOTH_SEMESTERS | PASS |  |
| Data separation | UCI tables contain no invented dates/terms/programmes/schools/modes/GPA | PASS | [] |
| Data separation | no synthetic identifiers inside UCI tables | PASS |  |
| Data separation | no synthetic file mixes UCI rows (no combined population or totals) | PASS |  |
| Calendar | term dates ordered (start < census < end) and terms do not overlap | PASS |  |
| Calendar | term_status consistent with the as-of date (COMPLETED iff end <= as-of; FUTURE iff start > as-of) | PASS |  |
| Calendar | reporting_status / grades_final_available / census_passed consistent with the as-of date | PASS |  |
| Calendar | academic_year labels follow Fall Y + Spring/Summer Y+1 | PASS |  |
| Calendar | academic years span their terms and carry a status consistent with the as-of date | PASS |  |
| Future terms | grades_final = True exactly for completed terms (no future/in-progress term marked completed) | PASS |  |
| Future terms | final course grades exist only in completed terms | PASS |  |
| Timeline | no enrolment before admission (every enrolment term starts on/after its admission date) | PASS |  |
| Timeline | admission_date = start of entry term | PASS |  |
| Timeline | admitted application (submitted <= decided < admission, same programme/term) for every non-internal admission | PASS |  |
| Timeline | first enrolment of each admission is in its entry term (cohort census) | PASS |  |
| Timeline | every admission has at least one term enrolment | PASS |  |
| Timeline | study_term_number counts enrolled terms 1..n within each admission | PASS |  |
| Timeline | exactly one FIRST_ADMISSION per student, and it is the earliest | PASS |  |
| Timeline | programme changes / next degrees / readmissions link to a matching earlier outcome | PASS |  |
| Transfers | programme transfers valid: same level, different programme, next regular term, credits <= earned | PASS | 276 transfers |
| Timeline | no enrolment after graduation/withdrawal/dismissal/change in the same admission (outcome term = last enrolled term) | PASS |  |
| Timeline | no simultaneous enrolment in two programmes (one enrolment per student per term) | PASS |  |
| Timeline | a student's programme admissions never overlap | PASS |  |
| Timeline | at most one ACTIVE programme per student | PASS |  |
| Graduation | graduations valid: term-end date, completed term, not after as-of, credits, minimum duration, GPA | PASS | 1821 graduations checked |
| Timeline | outcome dates = end of outcome term, recorded on/after it, never after the as-of date | PASS |  |
| Timeline | outcome fields present exactly when an outcome exists (withdrawal type only for withdrawals) | PASS |  |
| Progression | prior_gap_terms recomputes from the enrolment history | PASS |  |
| Progression | no gap inside one admission exceeds the configured limit (3 regular terms) | PASS |  |
| Progression | missed-term withdrawal rule (> 3 regular terms -> UNOFFICIAL withdrawal at next census) recomputes | PASS | withdrawal dates consistent |
| Future terms | no enrolments, grades, charges, standing, admissions, cohorts, events or graduations in FUTURE terms | PASS | ['2027SP', '2027SU'] |
| Future terms | future-term applications are not enrolled and are decided on/before the as-of date (or PENDING) | PASS | 320 applications for ['2027SP'] |
| Future terms | in-progress term (census snapshot only): no final grades, GPA, standing, performance flags or graduations | PASS | 2109 in-progress enrolments |
| Future terms | no recorded event after the as-of date | PASS | latest event 2026-11-10 23:55:46 |
| Status history | status history recomputes from admissions and enrolments (admission event never overwritten) | PASS | 11007 events for 5556 admissions |
| GPA & standing | grade points match the grading scheme | PASS |  |
| GPA & standing | course credits earned follow the pass mark | PASS |  |
| GPA & standing | semester GPA and cumulative GPA recompute from course grades | PASS |  |
| GPA & standing | term and cumulative credits earned recompute from course grades (incl. transferred credits) | PASS |  |
| GPA & standing | academic standing (good / warning / probation / dismissed) recomputes, carried forward when ungraded | PASS |  |
| GPA & standing | exactly one standing row per completed term enrolment; none for incomplete terms | PASS |  |
| GPA & standing | poor-performance flag and pass ratio recompute with the configured rule | PASS |  |
| GPA & standing | DISMISSED outcome <=> DISMISSED standing | PASS | 383 dismissals |
| Cohorts | every student is in exactly one INSTITUTIONAL cohort | PASS |  |
| Cohorts | INSTITUTIONAL cohort = first admission term | PASS |  |
| Cohorts | exactly one LEVEL_ENTRY membership per student per level (first admission at that level) | PASS |  |
| Cohorts | frozen entry attributes equal the census-term enrolment | PASS |  |
| Cohorts | size_at_census equals member count | PASS |  |
| Finance | every charge belongs to an actual term enrolment | PASS |  |
| Finance | every term enrolment is billed tuition | PASS |  |
| Finance | charge amounts: positive fees, negative scholarships | PASS |  |
| Finance | financial holds recompute from charges and payments | PASS | 4111 holds |
| Finance | hold status_as_of consistent with release date | PASS |  |
| Finance | no registration while a financial hold is active | PASS |  |
| Finance | every registration block coincides with an active hold | PASS | 609 blocks |
| Finance | blocked students are not enrolled in the blocked term | PASS |  |
| Finance | account balances = charges - payments | PASS |  |
| Finance | past-due balances recompute at the as-of date | PASS |  |
| Finance | has_active_hold flag equals the recomputed active holds | PASS |  |
| Finance | payments are positive and validly dated on/before the as-of date | PASS |  |
| IT | successful logins only while the account is active | PASS | 128480 successful logins |
| IT | student account created before the first term starts | PASS |  |
| IT | one account per student | PASS |  |
| IT | server status uptime and downtime agree | PASS |  |
| IT | one incident per non-operational server day | PASS |  |
| Data warehouse | sync runs fail exactly on ETL/database outage days | PASS | 8 failed runs |
| Retention | retention membership = every INSTITUTIONAL cohort member + every base-term enrolment (no more, no less) | PASS | 36965 expected, 36965 found |
| Retention | retention outcomes recompute independently (retained same programme / transfer / completed / stopped out / left) | PASS | 31991 final member outcomes |
| Retention | retention rates recompute: retained / (cohort - completed); programme retention; completions separate | PASS | 56 final comparisons |
| Retention | retained + completed + continuing (optional summer) + stopped out + left = denominator (100 %) | PASS |  |
| Retention | optional Summer: students enrolled the following Fall are never classified as stopped out or left | PASS | 1366 continuing summer non-enrollees |
| Retention | programme retained <= institutionally retained; retained excludes graduates | PASS |  |
| Retention | filtered groups (level, school, programme, mode, load) add up to the whole comparison | PASS |  |
| Retention | incomplete comparisons publish no rate | PASS | 6 incomplete comparisons |
| Retention | first-year Fall 2025 -> Fall 2026 cohort retention is FINAL_CENSUS_SNAPSHOT (Fall 2026 census passed, term in progress) | PASS | [{'denominator': 411, 'institutional_retention_rate': 0.8516, 'programme_retention_rate': 0.8297}] |
| Retention | Spring 2026 -> Spring 2027 and Summer 2026 -> Summer 2027 are INCOMPLETE (future terms) | PASS |  |
| Retention | no FINAL retention is measured in a future term | PASS |  |
| Retention | multi-year cohort retention: enrolled + completed + on gap + left = cohort size | PASS |  |
| Graduation | one graduation record per LEVEL_ENTRY cohort member | PASS | 5154 members, 5154 records |
| Graduation | graduation records recompute independently (window, maturity, status, dates, time-to-degree) | PASS | 5154 records |
| Graduation | final graduation rates recompute (UG 6 y, Master's 4 y, Doctorate 6 y; mature cohorts only) | PASS | {'UNDERGRADUATE': '694/1355 = 51.2%', 'MASTERS': '472/738 = 64.0%', 'DOCTORATE': '121/173 = 69.9%'} |
| Graduation | immature cohorts publish no final graduation rate | PASS |  |
| Graduation | configured windows are UG 6, Master's 4, Doctorate 6 years (project-configured reporting assumptions) | PASS | {'UNDERGRADUATE': 6, 'MASTERS': 4, 'DOCTORATE': 6} |
| Graduation | graduates are kept separate from enrolled students (no enrolment in a graduated admission after graduation) | PASS |  |
| Graduation | time-to-degree summary covers every graduation record with a graduation date | PASS |  |
| Enrolment | enrolment by term x school x programme x level x mode x load x gender x residency x nationality sums to headcount | PASS |  |
| Enrolment | the in-progress term is labelled CENSUS_SNAPSHOT_ONLY in enrolment outputs | PASS |  |
| Enrolment | academic-year unduplicated headcount recomputes | PASS |  |
| Performance | performance outputs use completed terms only | PASS |  |
| Performance | credit-weighted term GPA by term and level recomputes from course grades | PASS |  |
| Performance | standing counts add up to completed enrolments | PASS |  |

</details>

Key results (synthetic only):

```json
{
  "students": 5000,
  "admissions_by_entry_type": {
    "FIRST_ADMISSION": 5000,
    "PROGRAMME_CHANGE": 276,
    "NEXT_DEGREE": 154,
    "READMISSION": 126
  },
  "outcomes_by_level": {
    "DOCTORATE": {
      "GRADUATED": 175,
      "ACTIVE": 168,
      "WITHDRAWN": 47,
      "DISMISSED": 45
    },
    "MASTERS": {
      "GRADUATED": 600,
      "ACTIVE": 347,
      "WITHDRAWN": 169,
      "DISMISSED": 168
    },
    "UNDERGRADUATE": {
      "ACTIVE": 1754,
      "GRADUATED": 1046,
      "WITHDRAWN": 591,
      "CHANGED_PROGRAMME": 276,
      "DISMISSED": 170
    }
  },
  "first_year_retention_2025FA_to_2026FA": {
    "denominator": 411,
    "completed": 0.0,
    "eligible_to_return": 411.0,
    "institutionally_retained": 350.0,
    "programme_retained": 341.0,
    "stopped_out": 33.0,
    "left": 28.0,
    "institutional_retention_rate": 0.8516,
    "programme_retention_rate": 0.8297,
    "reporting_label": "FINAL_CENSUS_SNAPSHOT"
  },
  "fall_to_fall_2025FA_to_2026FA": {
    "denominator": 2046,
    "completed": 331.0,
    "eligible_to_return": 1715.0,
    "institutionally_retained": 1512.0,
    "programme_retained": 1452.0,
    "stopped_out": 114.0,
    "left": 89.0,
    "institutional_retention_rate": 0.8816,
    "programme_retention_rate": 0.8466,
    "reporting_label": "FINAL_CENSUS_SNAPSHOT"
  },
  "spring_to_spring_2025SP_to_2026SP": {
    "denominator": 1807,
    "completed": 327.0,
    "eligible_to_return": 1480.0,
    "institutionally_retained": 1302.0,
    "programme_retained": 1259.0,
    "stopped_out": 91.0,
    "left": 87.0,
    "institutional_retention_rate": 0.8797,
    "programme_retention_rate": 0.8507,
    "reporting_label": "FINAL"
  },
  "summer_to_summer_2025SU_to_2026SU": {
    "denominator": 381,
    "completed": 111.0,
    "eligible_to_return": 270.0,
    "institutionally_retained": 76.0,
    "programme_retained": 75.0,
    "stopped_out": 20.0,
    "left": 23.0,
    "institutional_retention_rate": 0.2815,
    "programme_retention_rate": 0.2778,
    "reporting_label": "FINAL"
  },
  "final_graduation_rates": {
    "DOCTORATE": {
      "window_years": 6,
      "denominator": 173,
      "graduated_within_window": 121,
      "rate": 0.6994
    },
    "MASTERS": {
      "window_years": 4,
      "denominator": 738,
      "graduated_within_window": 472,
      "rate": 0.6396
    },
    "UNDERGRADUATE": {
      "window_years": 6,
      "denominator": 1355,
      "graduated_within_window": 694,
      "rate": 0.5122
    }
  },
  "final_cohort_entry_range": {
    "DOCTORATE": [
      "2016FA",
      "2020SU"
    ],
    "MASTERS": [
      "2016FA",
      "2022SU"
    ],
    "UNDERGRADUATE": [
      "2016FA",
      "2020SU"
    ]
  },
  "time_to_degree": {
    "DOCTORATE": {
      "graduates": 175,
      "median_years": 3.316,
      "mean_years": 3.74,
      "median_enrolled_terms": 9.0,
      "mean_gap_terms": 0.36
    },
    "MASTERS": {
      "graduates": 600,
      "median_years": 2.3,
      "mean_years": 2.425,
      "median_enrolled_terms": 5.0,
      "mean_gap_terms": 0.21
    },
    "UNDERGRADUATE": {
      "graduates": 1046,
      "median_years": 4.315,
      "mean_years": 4.908,
      "median_enrolled_terms": 10.0,
      "mean_gap_terms": 0.363
    }
  },
  "headcount_by_term_first_last": {
    "2016FA": 298,
    "2025FA": 2046,
    "2026FA": 2109
  }
}
```

## 7. Limitations

* All institutional records are **synthetic**; patterns are plausible, not empirical, and must not be presented as real results.
* UCI records cannot support term-based retention, graduation within 4/6 years, delivery mode, school/programme, or official GPA;
  they cover only the first study year and an outcome at normal duration. They remain a separate analytical zone.
* Placeholder names and rules have not been confirmed by the university; all thresholds are configurable.
* Doctorate research progress is simplified to research-credit registration; no thesis milestones, supervisors or examinations.
* No course sections, instructors, timetables, financial aid packages or refunds are modelled; finance amounts are demonstration values.
* IT data covers only the 180 days up to the as-of date; login events are sampled behaviour, not real system logs.
* Fall 2026 retention is a census snapshot; it can change if late withdrawals were modelled (they are not).
* Doctorate cohorts after Summer 2020 and UG cohorts after Summer 2020 / Master's after Summer 2022 are not yet mature.

## 8. Retention and graduation methodology

**Status at a census date** (priority order): ENROLLED (term enrolment in that term, any programme) > COMPLETED (graduated
on/before the census, not enrolled) > ON_GAP (an admission still open: stopped out) > LEFT (withdrawn/dismissed, not readmitted).

**Retention comparisons** (`registrar/retention_cohort_members.csv`, rates in `reports/metrics/retention_rates.csv`):

| Comparison | Eligible cohort (denominator) | Measured at |
|---|---|---|
| FIRST_YEAR_COHORT | INSTITUTIONAL cohort: students whose *first ever* admission is the base term, frozen at its census | census of the same season one year later (e.g. Fall 2025 -> Fall 2026) |
| FALL_TO_FALL | everyone enrolled at the Fall census | next Fall census |
| SPRING_TO_SPRING | everyone enrolled at the Spring census | next Spring census |
| SUMMER_TO_SUMMER | everyone enrolled at the Summer census | next Summer census |

* **Optional Summer**: a student not enrolled at a Summer comparison census but enrolled at the next Fall census is
  CONTINUING_SKIPPED_OPTIONAL_SUMMER, never stopped out, withdrawn or left (this includes programme transfers taking effect
  in the Fall). Summer comparisons publish the strict re-enrolment rate and a **summer continuation rate**
  = (retained + continuing) / (cohort - completed).
* **Who returned**: enrolled in the comparison term (institutional retention, any programme). **Programme retention** counts only
  students enrolled in the same programme; internal transfers count as institutionally retained (RETAINED_PROGRAMME_TRANSFER),
  graduates who started the next degree level count as RETAINED_NEXT_LEVEL.
* **Graduates** (COMPLETED_NOT_ENROLLED) are never counted as retained; they are reported separately as completions and removed
  from the rate denominator: `retention_rate = retained / (cohort - completed)`. The unadjusted rate `retained / cohort` is also published.
* **Incomplete comparisons** (comparison census after the as-of date, e.g. Spring 2026 -> Spring 2027) are labelled INCOMPLETE and publish no rate.
  Fall 2026 is in progress: its census has passed, so Fall 2025 -> Fall 2026 is published as **FINAL_CENSUS_SNAPSHOT**
  (census headcount only; no Fall 2026 grades, standing or graduations exist).
* Retention is computed person by person from enrolment and outcome records, **never from differences between total headcounts**.

**Graduation** (`registrar/graduation_records.csv`, rates in `reports/metrics/graduation_rates.csv`):
* Cohort: LEVEL_ENTRY (first admission at the level). Original admission date/term are kept; programme changes stay in the same cohort.
* Graduated within window = graduation date <= entry-term start + window (UG 6, Master's 4, Doctorate 6 years).
  These windows are **project-configured reporting assumptions** requested for this dashboard, not verified university policy.
* Same maturity rule for every level: a cohort is **mature** only when the window end is on/before the as-of date and every term
  ending in the window is completed. Only mature cohorts enter final rates; others are labelled "INCOMPLETE: graduation window still open".
* Time to degree = (graduation date - original admission date) / 365.25, plus enrolled terms and missed regular terms.

## 9. Assumptions and placeholder policies

* Every school, programme, course, calendar date, fee, grading scale, GPA threshold, standing rule, withdrawal rule and window is a
  **PLACEHOLDER** (`verification_status = PLACEHOLDER`, names suffixed "[synthetic placeholder]"). Verified values go to EXTERNAL_REFERENCE.
* Calendar: Fall 09-01 / census 09-15 / end 12-20; Spring 01-15 / 01-29 / 05-10; Summer 05-25 / 06-05 / 08-10 (placeholders).
* As-of date 2026-11-10: terms ending on/before it are COMPLETED_TERM; Fall 2026 is CENSUS_SNAPSHOT_ONLY; Spring/Summer 2027 are
  FUTURE_NOT_REPORTABLE (only 320 pending/decided applications exist for Spring 2027).
* Missed-term withdrawal (rule `SYN-WD-MISSED-TERMS`, configurable `academic.max_consecutive_missed_terms = 3`): a **synthetic business rule**.
  More than 3 consecutive missed regular terms records an UNOFFICIAL withdrawal at the census of the next missed term. It only fills the
  outcome fields of that admission and adds a status-history event; the admission record and history are never overwritten.
* GPA: demonstration 4-point scale, credit-weighted from final course grades (W excluded). Standing: CGPA >= minimum -> GOOD; otherwise
  WARNING -> PROBATION -> DISMISSED (dismissal only if the term GPA is also below the minimum). Terms without graded courses carry the
  previous standing forward (NOT_EVALUATED before the first graded term). Minimums UG 2.0, Master's/Doctorate 3.0 (placeholders).
* Poor performance (synthetic rule): term GPA below the level minimum or less than 50 % of graded credits passed.
* Home country is the placeholder code `ZZZ` ("Home country (placeholder - not configured)").

## 10. Machine learning status

**No machine-learning model has been trained, selected, tuned or evaluated.** The pipelines only process, generate and validate data; no dashboard development has started.

