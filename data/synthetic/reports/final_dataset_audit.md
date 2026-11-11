# Final Dataset Audit: University Institutional Analytics Dashboard

> **Synthetic institutional records are DEMONSTRATION DATA, NOT REAL UNIVERSITY RECORDS.** UCI records are real public data held in a
> separate zone. Every school, programme, rule and window below is a placeholder or a project-configured assumption.

| | |
|---|---|
| Audit date / dataset as-of date | 2026-11-10 / 2026-11-10 |
| Generation run | `SYN-RUN-1.1.0-S20261110` (generator 1.1.0, seed 20261110) |
| Method | Independent script reading only the generated CSV files (no import of the project's generator, metric or validator code); results compared with `reports/metrics/*.csv` |
| Validator after audit fixes | **476 / 476 checks passed** · pytest **36 / 36 passed** (31 planted-error tests) |
| Graduation reconciliation (re-run) | Independent CSV reconciliation: all counts and percentages agree. Validator `--skip-repro`: **473 / 473 passed** (the 3 reproducibility checks were not needed because no data changed). Graduation planted-error tests and the clean-sample test: **6 / 6 passed**. Manifest SHA-256 values unchanged, so no records were modified |
| Original UCI file | SHA-256 `3ef126de5cefff26eb11fbb4237f1a1401cb64b488e2f1d598c23cedeb4c45ae`: unchanged |

### Changes made during this audit (and why)
| # | Finding | Action |
|---|---|---|
| A1 | `reports/metrics/cohort_retention.csv` and `term_persistence.csv` were **stale outputs of generator 1.0.0**, inconsistent with the current data (e.g. 2016FA cohort: 242 vs 240 retained) | Moved (not deleted) to `reports/superseded_generator_1.0.0/` with a "do not use" README. Current equivalents: `retention_rates.csv`, `cohort_retention_multi_year.csv` |
| A2 | **Optional Summer misclassified.** In Summer 2025 → Summer 2026, 149 students who skipped the optional Summer but were enrolled in Fall 2026 were counted as "stopped out", and 2 students whose internal programme transfer took effect in Fall 2026 were counted as **LEFT** (same bucket as withdrawn/dismissed) | Retention definition corrected: such students are `CONTINUING_SKIPPED_OPTIONAL_SUMMER` (new columns `next_regular_term_id`, `continued_next_regular_term`; new rate `summer_continuation_rate`). Validator check and a planted-error test added. Only `retention_cohort_members.csv` and the data dictionary changed; every simulated record is byte-identical |

No other data was regenerated or modified.

---

## 1. Final dataset coverage matrix

| Dashboard feature | Supported | Source tables (synthetic zone) | UCI zone |
|---|---|---|---|
| Enrolment per semester / academic year | ✅ | `term_enrolments`, `reports/metrics/enrolment_by_term.csv`, `enrolment_by_academic_year.csv` | ❌ (no calendar terms) |
| Enrolment by programme / school | ✅ | `term_enrolments.programme_id / school_id` → `reference/programmes`, `schools` | ❌ (UCI course categories are not programmes) |
| Enrolment by nationality / gender | ✅ | `students` → `reference/nationalities`, `gender_categories` | ✅ separately (UCI demographics) |
| Online vs face-to-face; full- vs part-time | ✅ | `term_enrolments.delivery_mode / study_load` | ❌ (UCI daytime/evening only) |
| Semester GPA, cumulative GPA | ✅ | `term_enrolments`, `course_enrolments` | ❌ (UCI has 0-20 grades, not GPA) |
| Standing, warning, probation, poor performance | ✅ | `academic_standing`, `term_enrolments.poor_performance_flag` | ❌ |
| Performance trends by semester / programme / school | ✅ | `reports/metrics/performance_by_term.csv` | ❌ |
| First-year retention Fall 2025 → Fall 2026 | ✅ (census snapshot) | `retention_cohort_members`, `retention_rates.csv` | ❌ |
| Fall→Fall, Spring→Spring, Summer→Summer | ✅ | same | ❌ |
| Institutional vs programme retention, transfers | ✅ | same | ❌ |
| Graduation UG 6 / Master's 4 / Doctorate 6 years | ✅ (mature cohorts) | `graduation_records`, `graduation_rates.csv` | ❌ (outcome at normal duration only) |
| Time to degree | ✅ | `graduation_records`, `time_to_degree.csv` | ❌ |
| Status history (stop-out, return, withdrawal, …) | ✅ | `student_status_history` | ❌ |
| Admissions, finance, IT, sync history | ✅ | `admissions/`, `finance/`, `it/`, `data_warehouse/` | ❌ |

**Files inspected:** 47 data files (42 synthetic + 5 UCI), all documented in `schema/data_dictionary.csv` (643 column rows, 0 undocumented files, 0 empty descriptions); manifest SHA-256 values match every file. `data_quality_report.md` contains all 10 required sections.

| Metric file (`reports/metrics/`) | Rows | Columns |
|---|---:|---:|
| enrolment_by_term.csv | 7,880 | 13 |
| enrolment_by_academic_year.csv | 165 | 5 |
| performance_by_term.csv | 1,229 | 15 |
| retention_rates.csv | 2,198 | 25 |
| cohort_retention_multi_year.csv | 93 | 12 |
| graduation_rates.csv | 134 | 16 |
| time_to_degree.csv | 3 | 6 |

## 2. Enrolment metric coverage

- `enrolment_by_term.csv` columns: term_id, academic_year, reporting_status, level, school_id, programme_id, delivery_mode, study_load,
  gender, residency_status, nationality_iso3, headcount, credits_attempted. Distinct values: 31 terms, 11 academic years,
  24 programmes, 5 schools, 15 nationalities, 4 genders, 2 delivery modes, 2 loads.
- Headcount sums to the 31,965 term enrolments exactly. Term enrolments: 24,211 face-to-face / 7,754 online; 21,168 full-time / 10,797 part-time.
- **Joins:** 0 unmatched programme ids, 0 unmatched school ids, 0 enrolments whose school differs from the programme's school.
- Fall 2026 is labelled `CENSUS_SNAPSHOT_ONLY` in the enrolment output.
- **Placeholders:** 24/24 programmes and 5/5 schools have `is_placeholder = True`, `verification_status = PLACEHOLDER`, and a display name
  ending in "[synthetic placeholder]". No reference row is marked VERIFIED.

## 3. Academic performance metric coverage

- **Independent GPA recomputation:** 40 randomly chosen programme admissions (seed 42), 233 completed term rows, recomputed
  from course grades (credit-weighted, W excluded): **0 mismatches** for semester GPA and cumulative GPA. Example: SYN-000406 2018FA term
  GPA 3.675 / CGPA 3.5643 recomputed = file.
- Standing rows: 29,856 = completed term enrolments (one per completed term): GOOD 27,294 · WARNING 1,132 · PROBATION 944 ·
  DISMISSED 383 · NOT_EVALUATED 103. Poor-performance flag set on 3,355 completed terms.
- `performance_by_term.csv` aggregates by term × level, × school, × programme (credit-weighted term GPA, mean CGPA, standing counts, poor performance).
- **Fall 2026 (census snapshot):** 2,109 enrolments; 0 with term GPA, 0 with cumulative GPA, 0 with `grades_final = True`,
  0 course grades other than `IP`, 0 standing rows, 0 rows in the performance file. ✅

## 4. Retention metric results (independently recomputed = metric file)

Denominator rule: base population minus students who **graduated** before the comparison census (reported as completions, never as retained).

| | Fall 2025 → Fall 2026 | Spring 2025 → Spring 2026 | Summer 2025 → Summer 2026 | First-year cohort Fall 2025 → Fall 2026 |
|---|---:|---:|---:|---:|
| Base population (enrolled at base census) | 2,046 | 1,807 | 381 | 411 (first-ever admissions) |
| Excluded: graduated before comparison | 331 | 327 | 111 | 0 |
| **Eligible cohort** | **1,715** | **1,480** | **270** | **411** |
| Retained institutionally | 1,512 | 1,302 | 76 | 350 |
| … same programme | 1,452 | 1,259 | 75 | 341 |
| … changed programme (same level) | 32 | 23 | 0 | 9 |
| … moved to next degree level | 28 | 20 | 1 | 0 |
| Skipped optional Summer, enrolled next Fall | n/a | n/a | 151 | n/a |
| Stopped out (admission still open) | 114 | 91 | 20 | 33 |
| Withdrawn | 57 | 40 | 12 | 26 |
| Dismissed | 32 | 47 | 11 | 2 |
| Not retained (eligible − retained) | 203 | 178 | 194 | 61 |
| **Institutional retention** | **88.2 %** | **88.0 %** | **28.1 %** | **85.2 %** |
| **Programme retention** | **84.7 %** | **85.1 %** | **27.8 %** | **83.0 %** |
| Summer continuation (retained + continuing) | n/a | n/a | **84.1 %** | n/a |
| Label | FINAL_CENSUS_SNAPSHOT | FINAL | FINAL | FINAL_CENSUS_SNAPSHOT |

- **85.2 % vs 83.0 %:** 350 of 411 first-year entrants were enrolled anywhere in Fall 2026 (institutional retention); 9 of them had
  transferred to another programme, so only 341 were enrolled in their **entry** programme (programme retention 341/411 = 83.0 %).
  The 2.2-point gap is exactly the internal transfers.
- **Optional Summer:** `summer_counts_as_expected_term = false`. 0 of 386 unofficial withdrawals were recorded at a Summer census and
  0 stop-out events reference a Summer term, so no student was withdrawn for skipping Summer. After fix A2, the 151 Summer non-enrollees
  who continued in Fall 2026 are reported separately, not as stopped out or left. The strict Summer→Summer rate (28.1 %) measures Summer
  re-enrolment only; use the 84.1 % continuation rate for persistence.
- Fall 2026 comparisons are census snapshots (census 2026-09-15 passed; term not finished). Spring/Summer 2026 → 2027 are INCOMPLETE.
- Minor display note: `retention_rates.csv` stores rates to 4 decimals; 76/270 = 0.28148 is stored as 0.2815 (shown 28.2 % if rounded
  twice). Dashboards should display from the stored counts or round once.

## 5. Graduation metric results (reconciled from the CSV files)

Source files: `registrar/graduation_records.csv` (record level) and `reports/metrics/graduation_rates.csv` (rows with
`aggregation = MATURE_COHORTS_BY_LEVEL`). Both were recomputed independently and agree exactly.

**Reporting rules checked:**
- The windows come from `synthetic_config.toml` and appear on every record: Undergraduate 6, Master's 4, Doctorate 6 years. All are
  `PROJECT_CONFIGURED_REPORTING_ASSUMPTION`.
- A cohort is mature when the entry-term start plus the window falls on or before the as-of date (2026-11-10). The same rule applies to
  all levels, and the independent date calculation matched the stored `cohort_mature` flag for every record.
- **Numerator:** students who graduated at the level on or before the window end date (`GRADUATED_WITHIN_WINDOW`).
- **Denominator:** every member of the level's mature entry cohorts.

### 5.1 Graduation rates by level

| Level | Window (years) | Mature cohorts | Eligible mature cohort size | Graduated within window | Not graduated within window | Graduation rate | Immature cohorts excluded | Students in excluded cohorts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Undergraduate | 6 | 13 | 1,355 | 694 | 661 | 51.2 % | 18 | 2,125 |
| Master's | 4 | 19 | 738 | 472 | 266 | 64.0 % | 12 | 508 |
| Doctorate | 6 | 13 | 173 | 121 | 52 | 69.9 % | 18 | 255 |
| **Total** | | **45** | **2,266** | **1,287** | **979** | | **48** | **2,888** |

Mature entry terms: Undergraduate 2016FA–2020SU, Master's 2016FA–2022SU, Doctorate 2016FA–2020SU. Excluded (immature) cohorts start at
2021FA (Undergraduate and Doctorate) and 2023FA (Master's).

### 5.2 Arithmetic checks

| Level | Graduated + Not graduated = Eligible | Graduated ÷ Eligible × 100 | Reported | Agrees |
|---|---|---|---:|---|
| Undergraduate | 694 + 661 = 1,355 ✅ | 694 ÷ 1,355 × 100 = 51.22 % | 51.2 % | ✅ |
| Master's | 472 + 266 = 738 ✅ | 472 ÷ 738 × 100 = 63.96 % | 64.0 % | ✅ |
| Doctorate | 121 + 52 = 173 ✅ | 121 ÷ 173 × 100 = 69.94 % | 69.9 % | ✅ |

Percentages are rounded once, to one decimal place, from the counts. The metric file stores 0.5122, 0.6396 and 0.6994.

### 5.3 Bridge from all 1,821 graduations to the rate numerators

| | Undergraduate | Master's | Doctorate | Total |
|---|---:|---:|---:|---:|
| Graduations within window, mature cohorts (rate numerator) | 694 | 472 | 121 | 1,287 |
| Graduations after the window, mature cohorts (in the denominator, not the numerator) | 162 | 25 | 2 | 189 |
| Graduations in immature cohorts (excluded from final rates) | 190 | 103 | 52 | 345 |
| **All graduations** | **1,046** | **600** | **175** | **1,821** |

"Not graduated within window" (979) = 189 who graduated after the window + 790 mature-cohort members with no graduation at that level.

**Were the Undergraduate and Doctorate percentages omitted?** No. All three rates are present in `graduation_rates.csv`, in
`data_quality_report.md` (`final_graduation_rates`), in `README.md` §4 and in the previous summary.

## 6. Data integrity findings

### 6.1 Graduation record reconciliation

A graduation record is **one row per student per degree level entered** (one per LEVEL_ENTRY cohort membership). It records the
student's graduation outcome at that level. It is **not** one row per graduation.

| # | Measure | Value | How established |
|---|---|---:|---|
| 1 | Total graduation records | 5,154 | rows in `graduation_records.csv` |
| 2 | Unique students | 5,000 | all 5,000 synthetic students appear; none is missing |
| 3 | Unique programme admissions behind the records | 5,154 | each record joins to exactly one entry admission (`cohort_members.student_programme_id`); 0 unmatched |
| 4 | Records per student | 1 record: 4,851 students · 2 records: 144 · 3 records: 5 | 4,851×1 + 144×2 + 5×3 = 5,154 ✅ · 4,851 + 144 + 5 = 5,000 ✅ |
| 5 | Students with multiple records | 149 | Undergraduate + Master's 112 · Master's + Doctorate 32 · Undergraduate + Master's + Doctorate 5 (each record is at a different level) |
| 6 | Records with a completed graduation | 1,821 | 1,632 within window + 189 after window; equals the 1,821 GRADUATED admissions in `student_programmes.csv` |
| | … unique students who graduated | 1,770 | 1,719 graduated once and 51 graduated twice, at two different levels (1,719 + 2×51 = 1,821 ✅) |
| 7 | Records without a completed graduation | 3,333 | 2,109 enrolled in Fall 2026 · 1,064 left · 160 stopped out (1,821 + 3,333 = 5,154 ✅) |
| 8 | Duplicate or invalid records | 0 | see 6.2 |

**Earlier wording corrected:** the previous text said "4,851 students entered one level, 144 entered two, 5 entered three". Read as
"4,851 students have two records", it does not reconcile. The correct reading is 4,851 students with **one** record each, which
reconciles exactly (row 4). The data was always consistent; only the wording was ambiguous. No records were changed.

### 6.2 Exception checks

| Check | Exceptions |
|---|---:|
| Duplicate graduation record IDs | 0 |
| Duplicate (cohort, student) or (student, level) records | 0 / 0 |
| Record in a cohort that is not LEVEL_ENTRY, or level ≠ cohort level | 0 / 0 |
| LEVEL_ENTRY members without a record | 0 |
| Graduation date present without a graduated status (or the reverse) | 0 |
| Multiple graduations from the same programme / at the same level | 0 / 0 |
| Graduation on or before admission | 0 |
| Graduation after the as-of date | 0 |
| Graduation in a term that is not completed | 0 |
| Graduation record without a matching GRADUATED admission | 0 |
| Enrolled in the same programme after graduating | 0 |
| Graduates counted as retained in retention records | 0 |
| UCI identifiers in synthetic files / synthetic IDs in UCI files | 0 / 0 |

Other exceptions found: A1 (stale files) and A2 (Summer classification), both corrected above. **No open data integrity exceptions.**

## 7. Missing features

None of the requested dashboard features is missing. Not modelled (outside the current scope, documented as limitations): course
sections/instructors, financial aid packages and refunds, Doctorate thesis milestones, late (post-census) withdrawals in Fall 2026, real names.

## 8. Remaining assumptions and limitations

- All institutional data are **synthetic**; distributions are configurable assumptions, not calibrated to any institution. A model trained
  on them learns the generator's rules (e.g. latent ability/risk driving grades and attrition), not real student behaviour.
- Every school, programme, calendar date, fee, grading scale, GPA threshold, standing rule, the missed-term withdrawal rule
  (`SYN-WD-MISSED-TERMS`, > 3 missed regular terms) and the 6/4/6-year windows are placeholders or project-configured assumptions.
- Simulation warm-up: headcount grows from 298 (Fall 2016) and stabilises around 2,000 from 2022; early growth is an artefact.
- Fall 2026 is a census snapshot; recent cohorts are not mature (UG/Doctorate after 2020SU, Master's after 2022SU).
- UCI covers only the first year and an outcome at normal duration; it cannot support term retention, 4/6-year graduation, schools,
  programmes, delivery mode or GPA.

## 9. Separation of UCI and synthetic populations

Confirmed: UCI zone = 4,424 students, `data_source = UCI` only, in `data/processed/uci/`; synthetic zone = 5,000 students,
`data_source = SYNTHETIC` only, in `data/synthetic/`. No shared keys, 0 cross-zone identifiers, no file or metric combines the two
populations, and the raw UCI file is unchanged.

## 10. Recommendation

**Ready for feature engineering: yes.** Every metric was recomputed independently from the actual files with zero discrepancies after
the two corrections; keys, dates, joins, term statuses and zone separation are clean; the validator passes 476/476 and detects 31/31 planted errors.

**Ready for model training: yes on the data side, subject to these conditions (decisions for the project owner, not data defects):**
1. **Choose the zone per model.** Real predictive claims (e.g. dropout risk) should use the UCI zone; models on the synthetic zone are
   demonstrations of the dashboard pipeline only and must be labelled as such.
2. **Define the target and the prediction date** (e.g. "graduated within window", "retained next Fall") and build features only from
   records dated before that point, to avoid leakage. `standing`, `poor_performance_flag`, `outcome`, `graduation_status` and retention
   outcome columns are derived from outcomes and must not be used as features for related targets.
3. **Respect censoring:** exclude immature cohorts from graduation targets, incomplete comparisons from retention targets, and Fall 2026
   from any grade-based target.
4. Never pool UCI and synthetic rows in one training set.

No model training, selection, tuning or evaluation has been started.
