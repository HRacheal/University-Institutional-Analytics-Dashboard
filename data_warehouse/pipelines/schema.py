"""Documented schema of every generated file (Zone A UCI + Zone B/C synthetic).

Each column: (name, type, required, description[, allowed values]).
Types: id, str, int, float, bool, date, datetime.  required=True means the value may never be empty.
The validator enforces: exact column set, required values present, types parse, allowed values respected.
The data dictionary (data/synthetic/schema/data_dictionary.csv) is generated from this file.
"""
from __future__ import annotations

LEVELS = ["UNDERGRADUATE", "MASTERS", "DOCTORATE"]
MODES = ["FACE_TO_FACE", "ONLINE"]
LOADS = ["FULL_TIME", "PART_TIME"]
GENDERS = ["FEMALE", "MALE", "ANOTHER_GENDER", "NOT_DISCLOSED"]
SEASONS = ["FALL", "SPRING", "SUMMER"]
STANDINGS = ["GOOD", "WARNING", "PROBATION", "DISMISSED", "NOT_EVALUATED"]
OUTCOMES = ["ACTIVE", "GRADUATED", "CHANGED_PROGRAMME", "WITHDRAWN", "DISMISSED"]
STATUS_CODES = ["ADMITTED", "STOPPED_OUT", "RETURNED", "WITHDRAWN", "DISMISSED", "CHANGED_PROGRAMME", "GRADUATED"]
REPORTING = ["COMPLETED_TERM", "CENSUS_SNAPSHOT_ONLY", "FUTURE_NOT_REPORTABLE"]

SYN_COMMON = [("data_source", "str", True, "Always SYNTHETIC", ["SYNTHETIC"]),
              ("source_system", "str", True, "Departmental source system label",
               ["REFERENCE_PLACEHOLDER", "ADMISSIONS", "REGISTRAR", "FINANCE", "IT", "DATA_WAREHOUSE"]),
              ("generation_run_id", "id", True, "Generation run that produced the row (data_warehouse/generation_runs)")]
REF_COMMON = [("data_source", "str", True, "SYNTHETIC (placeholder) or EXTERNAL_REFERENCE (verified)", ["SYNTHETIC", "EXTERNAL_REFERENCE"]),
              ("verification_status", "str", True, "PLACEHOLDER or VERIFIED", ["PLACEHOLDER", "VERIFIED"]),
              ("source_reference", "str", False, "Document/URL proving the value (required when VERIFIED)"),
              ("verified_on", "date", False, "Verification date (required when VERIFIED)"),
              ("verified_by", "str", False, "Who verified it (required when VERIFIED)"),
              ("source_system", "str", True, "Always REFERENCE_PLACEHOLDER for generated reference rows", ["REFERENCE_PLACEHOLDER"]),
              ("generation_run_id", "id", True, "Generation run that produced the row")]


def C(*cols, common=SYN_COMMON):
    return list(cols) + common


SYNTHETIC_SCHEMA: dict[str, list] = {
    # ------------------------------------------------------------------ reference (Zone C, placeholders)
    "reference/academic_terms": C(
        ("term_id", "id", True, "Term code, e.g. 2025FA"), ("term_sequence", "int", True, "Strict chronological order"),
        ("season", "str", True, "Season", SEASONS), ("calendar_year", "int", True, "Calendar year of the term"),
        ("academic_year", "str", True, "Academic year, e.g. 2025/26 (Fall Y + Spring/Summer Y+1)"),
        ("start_date", "date", True, "First day"), ("census_date", "date", True, "Census (enrolment snapshot) date"),
        ("end_date", "date", True, "Last day"), ("term_status", "str", True, "Relative to as-of date", ["COMPLETED", "IN_PROGRESS", "FUTURE"]),
        ("reporting_status", "str", True, "What may be reported for the term", REPORTING),
        ("census_passed", "bool", True, "Census date on/before the as-of date"),
        ("grades_final_available", "bool", True, "Final grades/outcomes exist (completed term only)"),
        ("is_regular_term", "bool", True, "Fall or Spring"), ("accepts_admissions", "bool", True, "New students may start"),
        ("has_enrolment_data", "bool", True, "Term within the simulated enrolment period"),
        ("in_completed_reporting", "bool", True, "Included in completed-term historical reporting"), common=REF_COMMON),
    "reference/academic_years": C(
        ("academic_year", "id", True, "Academic year"), ("start_date", "date", True, "Start of its first term"),
        ("end_date", "date", True, "End of its last term"), ("terms", "str", True, "Terms in the year"),
        ("year_status", "str", True, "Relative to as-of date", ["COMPLETED", "IN_PROGRESS", "FUTURE"]), common=REF_COMMON),
    "reference/schools": C(("school_id", "id", True, "School key"), ("school_code", "str", True, "School code"),
                           ("name", "str", True, "Placeholder school name"), ("display_name", "str", True, "Name with [synthetic placeholder] label"),
                           ("is_placeholder", "bool", True, "True until verified"), common=REF_COMMON),
    "reference/programmes": C(
        ("programme_id", "id", True, "Programme key"), ("programme_code", "str", True, "Programme code"),
        ("name", "str", True, "Placeholder programme name"), ("display_name", "str", True, "Name with [synthetic placeholder] label"),
        ("is_placeholder", "bool", True, "True until verified"), ("school_id", "id", True, "FK schools"),
        ("level", "str", True, "Academic level", LEVELS), ("delivery_modes_offered", "str", True, "Pipe-separated delivery modes"),
        ("credits_required", "int", True, "Credits to graduate"), ("normal_duration_years_override", "float", False, "Optional override"),
        ("graduation_window_years_override", "float", False, "Optional override"), ("intake_weight", "float", True, "Relative intake popularity (generator)"),
        common=REF_COMMON),
    "reference/courses": C(("course_id", "id", True, "Course key"), ("programme_id", "id", True, "FK programmes"),
                           ("course_code", "str", True, "Course code"), ("title", "str", True, "Generic placeholder title"),
                           ("credits", "int", True, "Credits (0 = variable research credit)"), ("year_level", "int", True, "Curriculum year (9 = research)"),
                           ("course_type", "str", True, "Type", ["COURSEWORK", "RESEARCH"]), common=REF_COMMON),
    "reference/grading_schemes": C(("grading_scheme_id", "id", True, "Scheme key"), ("name", "str", True, "Scheme name"),
                                   ("display_label", "str", True, "Label used on dashboards"), ("scale_min", "float", True, "Minimum"),
                                   ("scale_max", "float", True, "Maximum"), ("letter_points", "str", True, "JSON letter -> grade points"),
                                   ("non_gpa_grades", "str", True, "Grades excluded from GPA"), common=REF_COMMON),
    "reference/rule_sets": C(
        ("rule_set_id", "id", True, "Rule set key"), ("name", "str", True, "Name"), ("version", "str", True, "Version"),
        ("applies_to", "str", True, "Population", ["INSTITUTIONAL", "UCI"]), ("is_official_policy", "bool", True, "Always False for placeholders"),
        ("standing_rules", "str", True, "Academic standing rule text"), ("withdrawal_rule_id", "id", True, "Withdrawal rule key"),
        ("withdrawal_rule_status", "str", True, "Status of the withdrawal rule", ["SYNTHETIC_BUSINESS_RULE", "VERIFIED_POLICY"]),
        ("withdrawal_rule", "str", True, "Withdrawal rule text"), ("poor_performance_rule", "str", True, "Poor-performance flag rule"),
        ("max_consecutive_missed_terms", "int", True, "Missed regular terms tolerated before withdrawal"),
        ("summer_counts_as_expected_term", "bool", True, "Whether a missed Summer is a gap"),
        ("summer_admission_enabled", "bool", True, "Summer admissions allowed"), ("gpa_rule", "str", True, "GPA calculation rule"),
        ("conferral_rule", "str", True, "Graduation date rule"), common=REF_COMMON),
    "reference/level_rules": C(
        ("rule_set_id", "id", True, "FK rule_sets"), ("level", "str", True, "Level", LEVELS),
        ("normal_duration_years", "float", True, "Normal programme length (placeholder)"),
        ("graduation_window_years", "int", True, "Graduation reporting window (UG 6, MA 4, DR 6)"),
        ("min_years_to_graduate", "float", True, "Earliest graduation after admission"), ("credits_required", "int", True, "Default credits"),
        ("pass_points", "float", True, "Minimum grade points earning credit"), ("good_standing_min_gpa", "float", True, "Standing threshold"),
        ("graduation_min_gpa", "float", True, "Minimum cumulative GPA to graduate"),
        ("window_basis", "str", True, "Basis of the window", ["PROJECT_CONFIGURED_REPORTING_ASSUMPTION", "VERIFIED_POLICY"]),
        ("note", "str", True, "Explanation"), common=REF_COMMON),
    "reference/fee_schedules": C(("academic_year", "id", True, "FK academic_years"), ("level", "str", True, "Level", LEVELS),
                                 ("tuition_per_credit", "float", True, "Tuition per credit"), ("registration_fee", "float", True, "Per term"),
                                 ("technology_fee", "float", True, "Per term"), ("online_fee_per_credit", "float", True, "Online surcharge per credit"),
                                 ("currency_code", "str", True, "Placeholder currency"), common=REF_COMMON),
    "reference/nationalities": C(("nationality_iso3", "id", True, "ISO 3166-1 alpha-3 (ZZZ = home country not configured)"),
                                 ("label", "str", True, "Country label"), ("residency_status", "str", True, "Implied residency", ["DOMESTIC", "INTERNATIONAL"]),
                                 common=REF_COMMON),
    "reference/gender_categories": C(("gender", "id", True, "Gender category", GENDERS), ("description", "str", True, "Description"), common=REF_COMMON),
    "reference/delivery_modes": C(("delivery_mode", "id", True, "Delivery mode", MODES), ("description", "str", True, "Description"), common=REF_COMMON),
    "reference/attendance_loads": C(("study_load", "id", True, "Attendance load", LOADS), ("description", "str", True, "Description"), common=REF_COMMON),
    "reference/academic_standing_codes": C(("standing", "id", True, "Standing", STANDINGS), ("description", "str", True, "Description"), common=REF_COMMON),
    "reference/student_status_codes": C(("status_code", "id", True, "Status event", STATUS_CODES), ("description", "str", True, "Description"), common=REF_COMMON),
    "reference/roles": C(("role_code", "id", True, "Role"), ("description", "str", True, "Description"), ("module_access", "str", True, "Modules"), common=REF_COMMON),
    "reference/servers": C(("server_id", "id", True, "Server"), ("description", "str", True, "Description"), ("system", "str", True, "System"),
                           ("environment", "str", True, "Environment"), common=REF_COMMON),
    # ------------------------------------------------------------------ admissions
    "admissions/applicants": C(("applicant_id", "id", True, "Applicant key"), ("gender", "str", True, "Gender", GENDERS),
                               ("nationality_iso3", "id", True, "FK nationalities"), ("residency_status", "str", True, "Residency", ["DOMESTIC", "INTERNATIONAL"]),
                               ("birth_year", "int", True, "Birth year only")),
    "admissions/applications": C(
        ("application_id", "id", True, "Application key"), ("applicant_id", "id", True, "FK applicants"),
        ("student_id", "id", False, "FK students when the applicant enrolled"), ("programme_id", "id", True, "FK programmes"),
        ("school_id", "id", True, "FK schools"), ("level", "str", True, "Level", LEVELS), ("entry_term_id", "id", True, "FK academic_terms"),
        ("application_type", "str", True, "Type", ["NEW", "NEXT_DEGREE", "READMISSION"]), ("submitted_date", "date", True, "Submitted"),
        ("decision", "str", True, "Decision", ["ADMITTED", "REJECTED", "ADMITTED_DECLINED", "WITHDRAWN_BY_APPLICANT", "WAITLISTED_NOT_OFFERED", "PENDING"]),
        ("decision_date", "date", False, "Decided (empty when PENDING)"), ("admission_score", "float", True, "0-100 synthetic score"),
        ("enrolled", "bool", True, "Became a term enrolment")),
    # ------------------------------------------------------------------ registrar
    "registrar/students": C(("student_id", "id", True, "Student key SYN-nnnnnn"), ("applicant_id", "id", True, "FK applicants"),
                            ("gender", "str", True, "Gender", GENDERS), ("nationality_iso3", "id", True, "FK nationalities"),
                            ("residency_status", "str", True, "Residency", ["DOMESTIC", "INTERNATIONAL"]), ("birth_year", "int", True, "Birth year only")),
    "registrar/student_programmes": C(
        ("student_programme_id", "id", True, "Admission-to-programme key"), ("student_id", "id", True, "FK students"),
        ("programme_id", "id", True, "FK programmes"), ("level", "str", True, "Level", LEVELS), ("school_id", "id", True, "FK schools"),
        ("entry_term_id", "id", True, "Original admission term"), ("admission_date", "date", True, "Original admission date (= entry term start)"),
        ("entry_type", "str", True, "How admitted", ["FIRST_ADMISSION", "PROGRAMME_CHANGE", "NEXT_DEGREE", "READMISSION"]),
        ("previous_student_programme_id", "id", False, "Earlier admission for change/next degree/readmission"),
        ("application_id", "id", False, "FK applications (empty for internal programme change)"),
        ("credits_transferred_in", "int", True, "Credits carried in"), ("scholarship_pct", "int", True, "Scholarship percentage", [0, 25, 50, 100]),
        ("outcome", "str", True, "Outcome as of the as-of date", OUTCOMES), ("outcome_term_id", "id", False, "Outcome term (empty if ACTIVE)"),
        ("outcome_date", "date", False, "Outcome date = end of outcome term"), ("outcome_recorded_date", "date", False, "Date the outcome was recorded"),
        ("withdrawal_type", "str", False, "FORMAL or UNOFFICIAL", ["FORMAL", "UNOFFICIAL"]), ("exit_reason", "str", False, "Exit reason"),
        ("rule_set_id", "id", True, "FK rule_sets")),
    "registrar/term_enrolments": C(
        ("term_enrolment_id", "id", True, "Term enrolment key"), ("student_programme_id", "id", True, "FK student_programmes"),
        ("student_id", "id", True, "FK students"), ("programme_id", "id", True, "FK programmes"), ("school_id", "id", True, "FK schools"),
        ("level", "str", True, "Level", LEVELS), ("term_id", "id", True, "FK academic_terms"), ("academic_year", "id", True, "FK academic_years"),
        ("term_sequence", "int", True, "Term order"), ("study_term_number", "int", True, "nth enrolled term in this admission"),
        ("delivery_mode", "str", True, "Delivery mode this term", MODES), ("study_load", "str", True, "Attendance load this term", LOADS),
        ("credits_attempted", "int", True, "Credits registered"), ("credits_earned", "int", False, "Credits passed (completed terms)"),
        ("gpa_credits", "int", False, "Graded credits (completed terms)"), ("term_gpa", "float", False, "Semester GPA from course grades"),
        ("cumulative_gpa", "float", False, "Cumulative GPA of this admission"), ("cumulative_credits_earned", "int", False, "Incl. transferred credits"),
        ("passed_credit_ratio", "float", False, "Passed share of graded credits"), ("poor_performance_flag", "bool", False, "Synthetic poor-performance rule"),
        ("grades_final", "bool", True, "Term completed and graded"), ("withdrew_during_term", "bool", True, "Withdrew after census"),
        ("prior_gap_terms", "int", True, "Regular terms missed before this enrolment"), ("grading_scheme_id", "id", True, "FK grading_schemes")),
    "registrar/course_enrolments": C(
        ("course_enrolment_id", "id", True, "Course registration key"), ("term_enrolment_id", "id", True, "FK term_enrolments"),
        ("student_programme_id", "id", True, "FK student_programmes"), ("student_id", "id", True, "FK students"),
        ("term_id", "id", True, "FK academic_terms"), ("course_id", "id", True, "FK courses"), ("credits", "int", True, "Credits"),
        ("delivery_mode", "str", True, "Delivery mode", MODES), ("attempt_number", "int", True, "Attempt of this course"),
        ("grade_letter", "str", True, "Letter, W or IP", ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F", "W", "IP"]),
        ("grade_points", "float", False, "Grade points (graded only)"), ("grade_status", "str", True, "Status", ["FINAL", "WITHDRAWN", "IN_PROGRESS"]),
        ("counts_in_gpa", "bool", True, "Included in GPA"), ("credits_earned", "int", False, "Credits earned (completed terms)")),
    "registrar/academic_standing": C(
        ("standing_id", "id", True, "Standing key"), ("term_enrolment_id", "id", True, "FK term_enrolments"),
        ("student_programme_id", "id", True, "FK student_programmes"), ("student_id", "id", True, "FK students"),
        ("term_id", "id", True, "FK academic_terms"), ("rule_set_id", "id", True, "FK rule_sets"),
        ("standing", "str", True, "Standing after the term (synthetic rule)", STANDINGS), ("reason_code", "str", True, "Rule branch"),
        ("cumulative_gpa", "float", False, "CGPA used"), ("term_gpa", "float", False, "Term GPA used"), ("min_gpa", "float", True, "Threshold used")),
    "registrar/cohorts": C(("cohort_id", "id", True, "Cohort key"), ("cohort_type", "str", True, "Type", ["INSTITUTIONAL", "LEVEL_ENTRY"]),
                           ("entry_term_id", "id", True, "FK academic_terms"), ("level", "str", False, "Level for LEVEL_ENTRY", LEVELS),
                           ("size_at_census", "int", True, "Frozen size"), ("frozen_at", "date", True, "Census date")),
    "registrar/cohort_members": C(("cohort_id", "id", True, "FK cohorts"), ("student_id", "id", True, "FK students"),
                                  ("student_programme_id", "id", True, "Entry admission"), ("level_at_entry", "str", True, "Level", LEVELS),
                                  ("programme_at_entry", "id", True, "FK programmes"), ("delivery_mode_at_entry", "str", True, "Mode", MODES),
                                  ("study_load_at_entry", "str", True, "Load", LOADS)),
    "registrar/student_status_history": C(
        ("status_event_id", "id", True, "Event key"), ("student_id", "id", True, "FK students"),
        ("student_programme_id", "id", True, "FK student_programmes"), ("status_code", "str", True, "Event", STATUS_CODES),
        ("term_id", "id", True, "Term of the event"), ("event_date", "date", True, "Event date"),
        ("status_after", "str", True, "Status after the event", ["ACTIVE", "ON_GAP", "WITHDRAWN", "DISMISSED", "CHANGED_PROGRAMME", "GRADUATED"]),
        ("rule_reference", "str", False, "Rule or note")),
    "registrar/retention_cohort_members": C(
        ("retention_record_id", "id", True, "Record key"), ("comparison_id", "id", True, "Comparison"),
        ("comparison_type", "str", True, "Type", ["FIRST_YEAR_COHORT", "FALL_TO_FALL", "SPRING_TO_SPRING", "SUMMER_TO_SUMMER"]),
        ("base_term_id", "id", True, "Base term"), ("base_census_date", "date", True, "Base census"),
        ("compare_term_id", "id", False, "Comparison term"), ("compare_census_date", "date", False, "Comparison census"),
        ("student_id", "id", True, "FK students"), ("base_programme_id", "id", True, "Programme in base term / at entry"),
        ("base_school_id", "id", True, "School"), ("base_level", "str", True, "Level", LEVELS), ("base_delivery_mode", "str", True, "Mode", MODES),
        ("base_study_load", "str", True, "Load", LOADS), ("is_final", "bool", True, "Comparison census passed"),
        ("reporting_label", "str", True, "FINAL / FINAL_CENSUS_SNAPSHOT / INCOMPLETE"),
        ("status_at_compare", "str", False, "Status at comparison census", ["ENROLLED", "COMPLETED", "ON_GAP", "LEFT"]),
        ("compare_programme_id", "id", False, "Programme in comparison term"), ("compare_level", "str", False, "Level", LEVELS),
        ("outcome_category", "str", False, "Outcome", ["RETAINED_SAME_PROGRAMME", "RETAINED_PROGRAMME_TRANSFER", "RETAINED_NEXT_LEVEL",
                                                      "COMPLETED_NOT_ENROLLED", "CONTINUING_SKIPPED_OPTIONAL_SUMMER", "STOPPED_OUT", "LEFT"]),
        ("institutionally_retained", "bool", False, "Enrolled in any programme"), ("programme_retained", "bool", False, "Enrolled in same programme"),
        ("completed_before_compare", "bool", False, "Graduated, not enrolled (excluded from retained)"),
        ("next_regular_term_id", "id", False, "Summer comparisons: next regular (Fall) term after the comparison summer"),
        ("continued_next_regular_term", "bool", False, "Summer comparisons: enrolled at that Fall census (optional Summer skipped, not a stop-out)")),
    "registrar/graduation_records": C(
        ("graduation_record_id", "id", True, "Record key"), ("cohort_id", "id", True, "FK cohorts (LEVEL_ENTRY)"),
        ("student_id", "id", True, "FK students"), ("level", "str", True, "Level", LEVELS), ("entry_term_id", "id", True, "Original admission term"),
        ("admission_date", "date", True, "Original admission date"), ("programme_at_entry", "id", True, "FK programmes"),
        ("school_at_entry", "id", True, "FK schools"), ("window_years", "int", True, "Reporting window"), ("window_end_date", "date", True, "Window end"),
        ("window_basis", "str", True, "Basis", ["PROJECT_CONFIGURED_REPORTING_ASSUMPTION", "VERIFIED_POLICY"]),
        ("cohort_mature", "bool", True, "Full observation window completed"),
        ("graduation_status", "str", True, "Status", ["GRADUATED_WITHIN_WINDOW", "GRADUATED_AFTER_WINDOW", "ENROLLED_NOT_GRADUATED",
                                                     "STOPPED_OUT_NOT_GRADUATED", "LEFT_NOT_GRADUATED"]),
        ("graduated_programme_id", "id", False, "Programme graduated from"), ("graduation_term_id", "id", False, "Graduation term"),
        ("graduation_date", "date", False, "Graduation date"), ("time_to_degree_years", "float", False, "Calendar years admission -> graduation"),
        ("enrolled_terms_to_degree", "int", False, "Enrolled terms"), ("gap_terms_to_degree", "int", False, "Missed regular terms"),
        ("graduated_within_window", "bool", False, "Known when mature or graduated"), ("graduation_eligible_by_rules", "bool", True,
                                                                                       "Credits, minimum years and GPA met at latest completed term"),
        ("counts_in_final_rate", "bool", True, "Included in final graduation rates")),
    # ------------------------------------------------------------------ finance
    "finance/charges": C(("charge_id", "id", True, "Charge key"), ("student_id", "id", True, "FK students"),
                         ("student_programme_id", "id", True, "FK student_programmes"), ("term_id", "id", True, "FK academic_terms"),
                         ("charge_type", "str", True, "Type", ["TUITION", "REGISTRATION_FEE", "TECHNOLOGY_FEE", "ONLINE_LEARNING_FEE", "SCHOLARSHIP"]),
                         ("amount", "float", True, "Amount (scholarship negative)"), ("charge_date", "date", True, "Posted"),
                         ("due_date", "date", True, "Due"), ("currency_code", "str", True, "Placeholder currency")),
    "finance/payments": C(("payment_id", "id", True, "Payment key"), ("student_id", "id", True, "FK students"),
                          ("term_id", "id", False, "Term paid for (empty for hold resolution)"), ("payment_date", "date", True, "Date"),
                          ("amount", "float", True, "Positive amount"), ("method", "str", True, "Method", ["CARD", "BANK_TRANSFER", "SPONSOR"]),
                          ("payment_type", "str", True, "Type", ["SCHEDULED", "HOLD_RESOLUTION"])),
    "finance/financial_holds": C(("hold_id", "id", True, "Hold key"), ("student_id", "id", True, "FK students"),
                                 ("hold_type", "str", True, "Type", ["PAST_DUE_BALANCE"]), ("placed_date", "date", True, "Placed"),
                                 ("released_date", "date", False, "Released (empty if active)"), ("past_due_at_placement", "float", True, "Past-due amount"),
                                 ("status_as_of", "str", True, "Status", ["ACTIVE", "RELEASED"]), ("blocks_registration", "bool", True, "Blocks registration")),
    "finance/registration_blocks": C(("block_id", "id", True, "Block key"), ("student_id", "id", True, "FK students"),
                                     ("student_programme_id", "id", True, "FK student_programmes"), ("term_id", "id", True, "Blocked term"),
                                     ("registration_date", "date", True, "Registration attempt"), ("reason", "str", True, "Reason", ["ACTIVE_FINANCIAL_HOLD"])),
    "finance/account_balances": C(("student_id", "id", True, "FK students"), ("as_of_date", "date", True, "Snapshot date"),
                                  ("total_charged", "float", True, "Sum of charges"), ("total_paid", "float", True, "Sum of payments"),
                                  ("outstanding_balance", "float", True, "Charged - paid"), ("past_due_balance", "float", True, "Overdue amount"),
                                  ("has_active_hold", "bool", True, "Active hold"), ("currency_code", "str", True, "Placeholder currency")),
    # ------------------------------------------------------------------ IT
    "it/user_accounts": C(("account_id", "id", True, "Account key"), ("username", "str", True, "Username"),
                          ("account_type", "str", True, "Type", ["STUDENT", "STAFF"]), ("person_id", "id", True, "student_id or staff_id"),
                          ("role_code", "id", True, "FK roles"), ("department", "str", False, "Staff department"),
                          ("created_date", "date", True, "Created"), ("status_as_of", "str", True, "Status", ["ACTIVE", "DISABLED"]),
                          ("mfa_enabled", "bool", True, "MFA")),
    "it/account_status_events": C(("event_id", "id", True, "Event key"), ("account_id", "id", True, "FK user_accounts"),
                                  ("event", "str", True, "Event", ["ACTIVATED", "DISABLED", "REACTIVATED"]), ("event_date", "date", True, "Date")),
    "it/staff": C(("staff_id", "id", True, "Staff key"), ("department", "str", True, "Department"), ("role_code", "id", True, "FK roles"),
                  ("hire_date", "date", True, "Hired"), ("end_date", "date", False, "Left")),
    "it/login_events": C(("login_id", "id", True, "Login key"), ("account_id", "id", True, "FK user_accounts"),
                         ("event_time", "datetime", True, "Timestamp"), ("system", "str", True, "Target system"),
                         ("server_id", "id", True, "FK servers"), ("auth_server_id", "id", True, "Authentication server"),
                         ("success", "bool", True, "Succeeded"), ("failure_reason", "str", False, "Reason",
                                                                 ["ACCOUNT_DISABLED", "SERVICE_UNAVAILABLE", "WRONG_PASSWORD"]),
                         ("channel", "str", True, "Channel", ["WEB", "MOBILE"])),
    "it/server_status_daily": C(("server_id", "id", True, "FK servers"), ("status_date", "date", True, "Day"),
                                ("status", "str", True, "Status", ["OPERATIONAL", "DEGRADED", "OUTAGE"]), ("uptime_pct", "float", True, "Uptime %"),
                                ("downtime_minutes", "float", True, "Downtime"), ("cpu_avg_pct", "float", True, "CPU"), ("memory_avg_pct", "float", True, "Memory")),
    "it/incidents": C(("incident_id", "id", True, "Incident key"), ("server_id", "id", True, "FK servers"),
                      ("severity", "str", True, "Severity", ["MINOR", "MAJOR"]), ("started_at", "datetime", True, "Start"),
                      ("resolved_at", "datetime", True, "End"), ("downtime_minutes", "float", True, "Minutes"), ("description", "str", True, "Text")),
    # ------------------------------------------------------------------ data warehouse
    "data_warehouse/sync_runs": C(("run_id", "id", True, "Run key"), ("extracted_system", "str", True, "Source system extracted",
                                                                       ["ADMISSIONS", "REGISTRAR", "FINANCE", "IT"]),
                                  ("run_date", "date", True, "Night of run"), ("started_at", "datetime", True, "Start"),
                                  ("status", "str", True, "Status", ["SUCCESS", "FAILED"]), ("extract_from_date", "date", True, "From"),
                                  ("extract_to_date", "date", True, "To"), ("rows_extracted", "int", True, "Changed rows"),
                                  ("failure_reason", "str", False, "Reason")),
    "data_warehouse/generation_runs": [("generation_run_id", "id", True, "Run key"), ("generator_version", "str", True, "Version"),
                                        ("random_seed", "int", True, "Seed"), ("config_sha256", "str", True, "Config fingerprint"),
                                        ("as_of_date", "date", True, "As-of date"), ("first_term", "id", True, "First term"),
                                        ("last_admission_term", "id", True, "Last admission term"), ("target_students", "int", True, "Students"),
                                        ("label", "str", True, "Synthetic label"), SYN_COMMON[0], SYN_COMMON[1]],
}

UCI_SCHEMA: dict[str, list] = {
    "uci_students": [("uci_student_id", "id", True, "UCI-nnnnnn (row number in the original file)"), ("uci_row_number", "int", True, "Row in data/raw/data.csv"),
                     ("data_source", "str", True, "Always UCI", ["UCI"]), ("gender", "str", True, "UCI Gender 1/0", ["MALE", "FEMALE"]),
                     ("nationality_code", "int", True, "UCI Nacionality code"), ("nationality_label", "str", True, "Label"),
                     ("is_international", "bool", True, "UCI International"), ("marital_status_code", "int", True, "UCI code"),
                     ("marital_status_label", "str", True, "Label"), ("age_at_enrollment", "int", True, "UCI Age at enrollment"),
                     ("uci_course_code", "int", True, "UCI course category (not a university programme)"), ("uci_course_label", "str", True, "Label"),
                     ("attendance_schedule", "str", True, "UCI daytime/evening", ["DAYTIME", "EVENING"]), ("application_mode_code", "int", True, "UCI code"),
                     ("application_mode_label", "str", True, "Label or UNKNOWN"), ("application_order", "int", True, "UCI"),
                     ("previous_qualification_code", "int", True, "UCI code"), ("previous_qualification_label", "str", True, "Label or UNKNOWN"),
                     ("previous_qualification_grade", "float", True, "UCI 0-200"), ("admission_grade", "float", True, "UCI 0-200"),
                     ("scholarship_holder", "bool", True, "UCI"), ("debtor", "bool", True, "UCI"), ("tuition_fees_up_to_date", "bool", True, "UCI"),
                     ("displaced", "bool", True, "UCI"), ("educational_special_needs", "bool", True, "UCI"),
                     ("outcome_at_normal_duration", "str", True, "UCI Target", ["GRADUATED", "DROPPED_OUT", "STILL_ENROLLED"]),
                     ("dq_flags", "str", False, "Data-quality flags")],
    "uci_semester_results": [("uci_student_id", "id", True, "FK uci_students"), ("data_source", "str", True, "UCI", ["UCI"]),
                             ("study_semester", "int", True, "Relative semester of year 1 (not a calendar term)", [1, 2]),
                             ("units_credited", "int", True, "UCI"), ("units_enrolled", "int", True, "UCI"), ("units_evaluated", "int", True, "UCI"),
                             ("units_approved", "int", True, "UCI"), ("units_without_evaluation", "int", True, "UCI"),
                             ("uci_grade_raw", "float", True, "UCI 0-20 grade as published"),
                             ("uci_mean_grade_passed_units_0_20", "float", False, "Mean grade of passed units (NOT an official GPA)"),
                             ("pass_rate", "float", False, "approved / enrolled"),
                             ("evaluation_status", "str", True, "Status", ["EVALUATED", "NO_UNITS_PASSED", "NOT_EVALUATED"]), ("dq_flags", "str", False, "Flags")],
    "uci_course_categories": [("uci_course_code", "id", True, "UCI code"), ("label", "str", True, "UCI label"),
                              ("attendance_schedule", "str", True, "Schedule", ["DAYTIME", "EVENING", "MIXED"]), ("student_count", "int", True, "Students"),
                              ("data_source", "str", True, "UCI", ["UCI"]), ("note", "str", True, "Not a university programme")],
    "code_lookups": [("category", "str", True, "Code list"), ("code", "int", True, "UCI code"), ("label", "str", True, "UCI documentation label"),
                     ("data_source", "str", True, "UCI", ["UCI"])],
}


def uci_source_records_schema() -> list:
    import pandas as pd
    from .common import RAW_UCI_FILE
    from .uci_processing import RENAME
    header = list(pd.read_csv(RAW_UCI_FILE, sep=";", nrows=0).columns)      # original column order
    cols = [("uci_row_number", "int", True, "Row in data/raw/data.csv"), ("data_source", "str", True, "UCI", ["UCI"])]
    for orig in header:
        new = RENAME[orig]
        typ = "str" if new == "target" else ("float" if any(x in new for x in ("grade", "rate", "gdp")) else "int")
        cols.append((new, typ, True, f"Original UCI column '{orig.strip()}' (value unchanged)"))
    return cols


def data_dictionary_rows() -> list[dict]:
    rows = []
    for zone, schema in (("SYNTHETIC", SYNTHETIC_SCHEMA), ("UCI", {**UCI_SCHEMA, "uci_source_records": uci_source_records_schema()})):
        for table, cols in schema.items():
            for c in cols:
                rows.append({"zone": zone, "file": (f"data/synthetic/{table}.csv" if zone == "SYNTHETIC" else f"data/processed/uci/{table}.csv"),
                             "column": c[0], "type": c[1], "required": c[2], "description": c[3],
                             "allowed_values": "|".join(map(str, c[4])) if len(c) > 4 else ""})
    return rows
