"""Term-by-term simulation of synthetic student lives (Admissions + Registrar + Finance).

One student is simulated at a time, in strict date order, so every record is linked:
application -> admission -> term enrolments -> course grades -> GPA/standing ->
fees/payments/holds -> stop-out / withdrawal / dismissal / programme change / graduation ->
readmission or next degree.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from .reference import LEVELS, PROGRAMMES, Term
from .rules import hold_active_on, hold_intervals, letter_for, next_standing, past_due


class Ids:
    def __init__(self, prefix: str):
        self.prefix, self.n = prefix, {}

    def next(self, kind: str, width: int = 7) -> str:
        self.n[kind] = self.n.get(kind, 0) + 1
        return f"{self.prefix}-{kind}-{self.n[kind]:0{width}d}" if kind else f"{self.prefix}-{self.n[kind]:06d}"


class Simulator:
    def __init__(self, cfg: dict, rng: np.random.Generator, terms: list[Term], courses: list[dict], fees: list[dict]):
        self.cfg, self.rng, self.terms = cfg, rng, terms
        self.as_of = date.fromisoformat(cfg["meta"]["as_of_date"])
        self.by_seq = {t.seq: t for t in terms}
        self.last_seq = next(t.seq for t in terms if t.term_id == cfg["meta"]["last_admission_term"])
        self.ids = Ids(cfg["meta"]["id_prefix"])
        self.fin = cfg["finance"]
        self.acad = cfg["academic"]
        self.grading = cfg["grading"]
        self.prog = {p[0]: {"school": p[1], "level": p[2], "name": p[3], "modes": p[4].split("|"), "w": p[5]} for p in PROGRAMMES}
        self.prog_by_level = {lv: [c for c, p in self.prog.items() if p["level"] == lv] for lv in LEVELS}
        self.coursework = {}
        self.research = {}
        for c in courses:
            if c["course_type"] == "RESEARCH":
                self.research[c["programme_id"]] = c["course_id"]
            else:
                self.coursework.setdefault(c["programme_id"], []).append((c["year_level"], c["course_id"]))
        self.fee = {(f["academic_year"], f["level"]): f for f in fees}
        self.out = {k: [] for k in ("applicants", "applications", "students", "student_programmes", "term_enrolments",
                                     "course_enrolments", "academic_standing", "charges", "payments",
                                     "financial_holds", "registration_blocks")}
        self.check_dates: dict[str, list[date]] = {}   # student_id -> hold check dates

    # ------------------------------------------------------------------ helpers
    def choice(self, items, weights=None):
        if weights is None:
            return items[int(self.rng.integers(len(items)))]
        w = np.asarray(weights, dtype=float)
        return items[int(self.rng.choice(len(items), p=w / w.sum()))]

    def pick_programme(self, level: str, exclude: str | None = None) -> str:
        codes = [c for c in self.prog_by_level[level] if c != exclude]
        return self.choice(codes, [self.prog[c]["w"] for c in codes])

    def next_regular(self, seq: int, k: int = 1) -> int | None:
        s, found = seq, 0
        while found < k:
            s += 1
            if s not in self.by_seq:
                return None
            if self.by_seq[s].is_regular:
                found += 1
        return s

    def admissible_after(self, seq: int, k: int) -> int | None:
        """k-th admission-accepting term after seq."""
        s, found = seq, 0
        summer_ok = self.cfg["calendar"]["summer_admission_enabled"]
        while found < k:
            s += 1
            if s not in self.by_seq:
                return None
            if self.by_seq[s].is_regular or summer_ok:
                found += 1
        return s

    def online_share(self, level: str, year: int) -> float:
        a, b = self.cfg["levels"][level]["online_share"]
        return a + (b - a) * min(max((year - 2016) / 10, 0), 1)

    # ------------------------------------------------------------------ people
    def new_person(self, level: str, entry: Term) -> dict:
        d = self.cfg["demographics"]
        genders = list(d["gender_weights"])
        intl = self.rng.random() < d["international_share"][level]
        countries = list(d["international_countries"])
        lo, hi = self.cfg["levels"][level]["entry_age"]
        age = int(min(hi + 10, lo + self.rng.gamma(2.0, (hi - lo) / 4)))
        return {
            "gender": self.choice(genders, list(d["gender_weights"].values())),
            "nationality_iso3": self.choice(countries, list(d["international_countries"].values())) if intl else d["home_country_iso3"],
            "residency_status": "INTERNATIONAL" if intl else "DOMESTIC",
            "birth_year": entry.calendar_year - age,
        }

    def add_application(self, applicant_id, student_id, programme, entry: Term, app_type, decision, enrolled,
                        score, earliest: date | None = None, today_cap: date | None = None) -> dict:
        latest_decision = entry.start - timedelta(days=7)
        submitted = entry.start - timedelta(days=int(self.rng.integers(45, 240)))
        if earliest and submitted <= earliest:
            submitted = earliest + timedelta(days=1)
        decided = submitted + timedelta(days=int(self.rng.integers(7, 45)))
        if decided > latest_decision:
            decided = max(submitted + timedelta(days=1), latest_decision)
        if today_cap and decided > today_cap:
            decided = None
        row = {
            "application_id": self.ids.next("APP"), "applicant_id": applicant_id, "student_id": student_id or "",
            "programme_id": programme, "school_id": self.prog[programme]["school"],
            "level": self.prog[programme]["level"], "entry_term_id": entry.term_id,
            "application_type": app_type, "submitted_date": submitted, "decision": decision,
            "decision_date": decided or "", "admission_score": round(float(np.clip(score, 0, 100)), 1),
            "enrolled": enrolled, "data_source": "SYNTHETIC",
        }
        self.out["applications"].append(row)
        return row

    # ------------------------------------------------------------------ main loop
    def run(self) -> dict:
        cfg = self.cfg
        intake_terms = [t for t in self.terms if t.seq <= self.last_seq and (t.is_regular or cfg["calendar"]["summer_admission_enabled"])]
        sw, g = cfg["intake"]["season_weights"], cfg["intake"]["yearly_growth"]
        w = np.array([sw[t.season] * (1 + g) ** (int(t.academic_year[:4]) - 2016) for t in intake_terms])
        counts = self.rng.multinomial(cfg["meta"]["target_students"], w / w.sum())
        levels, lw = list(cfg["intake"]["level_weights"]), list(cfg["intake"]["level_weights"].values())
        for term, n in zip(intake_terms, counts):
            for _ in range(int(n)):
                self.simulate_student(term, self.choice(levels, lw))
        self.add_non_enrolling_applications()
        return self.out

    def simulate_student(self, entry: Term, level: str) -> None:
        sid = self.ids.next("", 6)
        apl = self.ids.next("APL")
        person = self.new_person(level, entry)
        self.out["applicants"].append({"applicant_id": apl, **person, "data_source": "SYNTHETIC"})
        self.out["students"].append({"student_id": sid, "applicant_id": apl, **person, "data_source": "SYNTHETIC"})
        stu = {
            "id": sid, "applicant": apl, "ability": float(self.rng.normal()),
            "risk": float(self.rng.beta(1.5, 6.0)), "charges": [], "payments": [],
            "online_pref": None,
        }
        self.check_dates[sid] = []
        programme = self.pick_programme(level)
        app = self.add_application(apl, sid, programme, entry, "NEW", "ADMITTED", True,
                                   55 + 12 * stu["ability"] + self.rng.normal(0, 8))
        stint = {"programme": programme, "entry": entry, "entry_type": "FIRST_ADMISSION", "prev_sp": "",
                 "credits_in": 0, "passed": set(), "path_start": entry.start, "application_id": app["application_id"],
                 "study_load": None}
        while stint:
            stint = self.run_stint(stu, stint)
        # Only payments made on or before the as-of date are recorded; holds use the same rule as registration.
        pays = sorted((p for p in stu["payments"] if p["payment_date"] <= self.as_of),
                      key=lambda p: (p["payment_date"], p["amount"]))
        self.out["payments"].extend(pays)
        for placed, released, amount in hold_intervals(stu["charges"], pays, self.check_dates[sid], self.as_of,
                                                       self.fin["hold_threshold"]):
            self.out["financial_holds"].append({
                "hold_id": self.ids.next("HLD"), "student_id": sid, "hold_type": "PAST_DUE_BALANCE",
                "placed_date": placed, "released_date": released or "", "past_due_at_placement": amount,
                "status_as_of": "ACTIVE" if released is None else "RELEASED",
                "blocks_registration": True, "data_source": "SYNTHETIC"})

    # ------------------------------------------------------------------ one programme admission
    def run_stint(self, stu: dict, st: dict) -> dict | None:
        cfg, rng = self.cfg, self.rng
        prog = self.prog[st["programme"]]
        level = prog["level"]
        lv = cfg["levels"][level]
        entry: Term = st["entry"]
        sp_id = self.ids.next("SP")
        if stu["online_pref"] is None:
            stu["online_pref"] = bool(rng.random() < self.online_share(level, entry.calendar_year))
        load = st["study_load"] or ("FULL_TIME" if rng.random() < lv["full_time_share"] else "PART_TIME")
        sch_w = self.fin["scholarship_pct_weights"]
        scholarship = int(self.choice(list(sch_w), list(sch_w.values())))
        if level == "DOCTORATE" and load == "FULL_TIME" and rng.random() < self.fin["doctorate_full_funding_probability"]:
            scholarship = 100
        sp = {
            "student_programme_id": sp_id, "student_id": stu["id"], "programme_id": st["programme"], "level": level,
            "school_id": prog["school"], "entry_term_id": entry.term_id, "admission_date": entry.start,
            "entry_type": st["entry_type"], "previous_student_programme_id": st["prev_sp"],
            "application_id": st.get("application_id", ""), "credits_transferred_in": st["credits_in"],
            "scholarship_pct": scholarship, "outcome": "ACTIVE", "outcome_term_id": "", "outcome_date": "",
            "outcome_recorded_date": "", "withdrawal_type": "", "exit_reason": "",
            "rule_set_id": "DEMO-RULES-1", "data_source": "SYNTHETIC",
        }
        self.out["student_programmes"].append(sp)

        passed: set = set(st["passed"])
        attempts: dict = {}
        earned = st["credits_in"]
        coursework_earned = st["credits_in"] if level == "DOCTORATE" else 0
        pts = cred = 0.0
        standing = None
        missed = 0                 # consecutive missed regular terms
        pending_gap = 0
        never_return = False
        withdraw_boost = 1.0
        hold_missed = 0
        n_enrolled = 0
        last_enrolled: Term | None = None
        mode = None
        t = entry.seq
        first = True

        def finish(outcome, term: Term | None, recorded: date | None, wtype="", reason=""):
            sp.update(outcome=outcome, outcome_term_id=term.term_id if term else "",
                      outcome_date=term.end if term else "", outcome_recorded_date=recorded or "",
                      withdrawal_type=wtype, exit_reason=reason)

        while True:
            if t > self.last_seq:
                return None                        # still ACTIVE (enrolled or on a gap) at the as-of date
            term = self.by_seq[t]
            reg_date = term.start - timedelta(days=7)

            if not first:
                if term.season == "SUMMER":
                    if never_return or pending_gap or rng.random() >= lv["summer_take_probability"] or \
                            self.hold_active(stu, reg_date):
                        t += 1
                        continue
                else:
                    if never_return or pending_gap > 0:
                        if pending_gap > 0:
                            pending_gap -= 1
                        missed += 1
                        if missed > self.acad["max_consecutive_missed_terms"]:
                            finish("WITHDRAWN", last_enrolled, term.census, "UNOFFICIAL",
                                   "FINANCIAL_HOLD" if hold_missed else "STOPPED_ATTENDING")
                            return self.maybe_readmit(stu, sp, st, last_enrolled, term, passed, earned, load)
                        t += 1
                        continue
                    if self.hold_active(stu, reg_date):
                        if rng.random() < self.fin["hold_resolution_probability"] - 0.4 * stu["risk"]:
                            self.resolve_hold(stu, reg_date)
                        else:
                            self.out["registration_blocks"].append({
                                "student_id": stu["id"], "student_programme_id": sp_id, "term_id": term.term_id,
                                "registration_date": reg_date, "reason": "ACTIVE_FINANCIAL_HOLD",
                                "data_source": "SYNTHETIC"})
                            missed += 1
                            hold_missed += 1
                            if missed > self.acad["max_consecutive_missed_terms"]:
                                finish("WITHDRAWN", last_enrolled, term.census, "UNOFFICIAL", "FINANCIAL_HOLD")
                                return self.maybe_readmit(stu, sp, st, last_enrolled, term, passed, earned, load)
                            t += 1
                            continue
                    years_in = (term.start - entry.start).days / 365.25
                    lp = lv["leave_probability"]
                    p = lp["first_year"] if years_in < 1 else lp["second_year"] if years_in < 2 else lp["later"]
                    p *= {"WARNING": 1.8, "PROBATION": 2.5}.get(standing, 1.0)
                    p *= (1.4 if stu["ability"] < -1 else 1.0) * (1 + stu["risk"]) * withdraw_boost
                    withdraw_boost = 1.0
                    if rng.random() < min(p, 0.6):
                        missed += 1
                        if missed > self.acad["max_consecutive_missed_terms"]:   # same rule on every missed-term path
                            finish("WITHDRAWN", last_enrolled, term.census, "UNOFFICIAL", "STOPPED_ATTENDING")
                            return self.maybe_readmit(stu, sp, st, last_enrolled, term, passed, earned, load)
                        if rng.random() < lv["return_probability"]:
                            pending_gap = int(self.choice([0, 1, 2], [0.55, 0.30, 0.15]))
                        elif rng.random() < 0.5:
                            finish("WITHDRAWN", last_enrolled, term.start, "FORMAL", "PERSONAL_OR_OTHER")
                            return self.maybe_readmit(stu, sp, st, last_enrolled, term, passed, earned, load)
                        else:
                            never_return = True
                        t += 1
                        continue
            else:
                # first term of an admission: registration requires clearing any old hold
                if self.hold_active(stu, reg_date):
                    self.resolve_hold(stu, reg_date)

            # ---------------- enrol in this term
            if term.is_regular and rng.random() < 0.06 and not first:
                load = "PART_TIME" if load == "FULL_TIME" else "FULL_TIME"
            offered = prog["modes"]
            want_online = stu["online_pref"] if (mode is None or rng.random() < 0.9) else not stu["online_pref"]
            mode = "ONLINE" if (want_online and "ONLINE" in offered) else "FACE_TO_FACE"
            stu["online_pref"] = want_online
            n_enrolled += 1
            prior_gap = missed
            missed = 0
            hold_missed = 0
            final = term.status == "COMPLETED"
            te_id = self.ids.next("TE")
            term_withdrawn = final and bool(rng.random() < self.acad["withdrawal_during_term_probability"])
            courses = self.choose_courses(st["programme"], level, lv, load, term, passed, coursework_earned)
            term_effect = rng.normal(0, 0.3)
            t_pts = t_cred = t_earned = attempted = 0.0
            for cid, credits in courses:
                attempted += credits
                attempts[cid] = attempts.get(cid, 0) + 1
                attempt = attempts[cid]
                if not final:
                    letter, gp, status = "IP", None, "IN_PROGRESS"
                elif term_withdrawn or rng.random() < self.acad["course_withdrawal_probability"] + (0.03 if stu["ability"] < -1 else 0):
                    letter, gp, status = "W", None, "WITHDRAWN"
                else:
                    score = lv["grade_base"] + 0.6 * stu["ability"] + term_effect + rng.normal(0, 0.55) + \
                        (self.acad["online_grade_adjustment"] if mode == "ONLINE" else 0)
                    letter, gp = letter_for(score, self.grading["letters"], self.grading["points"], self.grading["f_below"])
                    status = "FINAL"
                ce = {"course_enrolment_id": self.ids.next("CE", 8), "term_enrolment_id": te_id,
                      "student_programme_id": sp_id, "student_id": stu["id"], "term_id": term.term_id,
                      "course_id": cid, "credits": credits, "delivery_mode": mode, "attempt_number": attempt,
                      "grade_letter": letter, "grade_points": gp, "grade_status": status,
                      "counts_in_gpa": gp is not None, "credits_earned": "", "data_source": "SYNTHETIC"}
                if gp is not None:
                    t_pts += round(gp * 10) * credits      # exact integer tenths of grade points
                    t_cred += credits
                    if gp >= lv["pass_points"]:
                        t_earned += credits
                        passed.add(cid)
                        if cid != self.research.get(st["programme"]):
                            coursework_earned += credits if level == "DOCTORATE" else 0
                    ce["credits_earned"] = credits if gp >= lv["pass_points"] else 0
                elif final:
                    ce["credits_earned"] = 0
                self.out["course_enrolments"].append(ce)
            pts += t_pts
            cred += t_cred
            if final:
                earned += t_earned
            term_gpa = round(t_pts / (10 * t_cred), 4) if t_cred else None
            cgpa = round(pts / (10 * cred), 4) if cred else None
            ratio = round(t_earned / t_cred, 4) if (final and t_cred) else None
            poor = (term_gpa < lv["good_standing_min_gpa"] or ratio < self.cfg["reporting"]["poor_performance_pass_ratio_below"])                 if ratio is not None else None
            self.out["term_enrolments"].append({
                "term_enrolment_id": te_id, "student_programme_id": sp_id, "student_id": stu["id"],
                "programme_id": st["programme"], "school_id": prog["school"], "level": level,
                "term_id": term.term_id, "academic_year": term.academic_year, "term_sequence": term.seq,
                "study_term_number": n_enrolled, "delivery_mode": mode, "study_load": load,
                "credits_attempted": attempted, "credits_earned": t_earned if final else "",
                "gpa_credits": t_cred if final else "", "term_gpa": term_gpa if final else "",
                "cumulative_gpa": cgpa if final else "", "cumulative_credits_earned": earned if final else "",
                "passed_credit_ratio": ratio if ratio is not None else "",
                "poor_performance_flag": poor if poor is not None else "",
                "grades_final": final, "withdrew_during_term": term_withdrawn, "prior_gap_terms": prior_gap,
                "grading_scheme_id": "DEMO4", "data_source": "SYNTHETIC",
            })
            self.bill_term(stu, sp, term, attempted, mode, level)
            last_enrolled = term
            first = False
            if term_withdrawn:
                withdraw_boost = 3.0

            if not final:
                return None                        # in-progress term (Fall 2026): stays ACTIVE

            if term_gpa is not None and cgpa is not None:
                standing, reason = next_standing(standing, cgpa, term_gpa, lv["good_standing_min_gpa"])
                self.out["academic_standing"].append({
                    "standing_id": self.ids.next("STD"), "term_enrolment_id": te_id, "student_programme_id": sp_id,
                    "student_id": stu["id"], "term_id": term.term_id, "rule_set_id": "DEMO-RULES-1",
                    "standing": standing, "reason_code": reason, "cumulative_gpa": cgpa, "term_gpa": term_gpa,
                    "min_gpa": lv["good_standing_min_gpa"], "data_source": "SYNTHETIC"})
                if standing == "DISMISSED":
                    finish("DISMISSED", term, term.end, "", "ACADEMIC_STANDING")
                    return self.maybe_readmit(stu, sp, st, term, term, passed, earned, load, dismissed=True)
            else:
                # completed term without graded courses (all withdrawn): standing is carried forward unchanged
                self.out["academic_standing"].append({
                    "standing_id": self.ids.next("STD"), "term_enrolment_id": te_id, "student_programme_id": sp_id,
                    "student_id": stu["id"], "term_id": term.term_id, "rule_set_id": "DEMO-RULES-1",
                    "standing": standing or "NOT_EVALUATED",
                    "reason_code": "NO_GRADED_COURSES_CARRIED_FORWARD" if standing else "NO_GRADED_COURSES_YET",
                    "cumulative_gpa": cgpa if cgpa is not None else "", "term_gpa": "",
                    "min_gpa": lv["good_standing_min_gpa"], "data_source": "SYNTHETIC"})

            years = (term.end - st["path_start"]).days / 365.25
            if earned >= lv["credits_required"] and years >= lv["min_years_to_graduate"] and \
                    cgpa is not None and cgpa >= lv["graduation_min_gpa"]:
                finish("GRADUATED", term, term.end)
                return self.maybe_next_degree(stu, sp, level, term, load)

            if level == "UNDERGRADUATE" and term.is_regular and n_enrolled <= 4 and \
                    rng.random() < self.acad["programme_change_probability"]:
                nxt = self.next_regular(term.seq)
                if nxt is not None and nxt <= self.last_seq:
                    finish("CHANGED_PROGRAMME", term, term.end, "", "PROGRAMME_CHANGE")
                    lo, hi = self.acad["programme_change_credit_transfer"]
                    moved = int(earned * rng.uniform(lo, hi) // 3 * 3)
                    return {"programme": self.pick_programme(level, exclude=st["programme"]),
                            "entry": self.by_seq[nxt], "entry_type": "PROGRAMME_CHANGE", "prev_sp": sp_id,
                            "credits_in": moved, "passed": set(), "path_start": st["path_start"],
                            "application_id": "", "study_load": load}
            t += 1

    # ------------------------------------------------------------------ courses
    def choose_courses(self, programme, level, lv, load, term: Term, passed: set, coursework_earned) -> list[tuple]:
        rng = self.rng
        if level == "DOCTORATE" and coursework_earned >= lv["coursework_credits"]:
            key = "research_credits_summer" if term.season == "SUMMER" else (
                "research_credits_full_time" if load == "FULL_TIME" else "research_credits_part_time")
            return [(self.research[programme], lv[key])]
        key = "courses_summer" if term.season == "SUMMER" else (
            "courses_full_time" if load == "FULL_TIME" else "courses_part_time")
        n = int(self.choice(lv[key]))
        pool = [(y, cid) for y, cid in self.coursework[programme] if cid not in passed]
        pool.sort(key=lambda x: (x[0], rng.random()))
        picked = pool[:n]
        if not picked and level == "DOCTORATE":
            return [(self.research[programme], lv["research_credits_part_time"])]
        if not picked:   # every course passed but graduation GPA not met: retake courses to raise GPA
            allc = [cid for _y, cid in self.coursework[programme]]
            picked = [(0, allc[int(i)]) for i in rng.choice(len(allc), size=n, replace=False)]
        return [(cid, lv["course_credits"]) for _y, cid in picked]

    # ------------------------------------------------------------------ finance
    def bill_term(self, stu, sp, term: Term, credits, mode, level):
        f, rng = self.fin, self.rng
        fee = self.fee[(term.academic_year, level)]
        due = term.census + timedelta(days=f["due_days_after_census"])
        self.check_dates[stu["id"]].append(due + timedelta(days=f["hold_check_days_after_due"]))
        lines = [("TUITION", credits * fee["tuition_per_credit"]), ("REGISTRATION_FEE", fee["registration_fee"]),
                 ("TECHNOLOGY_FEE", fee["technology_fee"])]
        if mode == "ONLINE":
            lines.append(("ONLINE_LEARNING_FEE", credits * fee["online_fee_per_credit"]))
        if sp["scholarship_pct"]:
            lines.append(("SCHOLARSHIP", -credits * fee["tuition_per_credit"] * sp["scholarship_pct"] / 100))
        net = 0.0
        for kind, amt in lines:
            amt = round(amt, 2)
            net += amt
            c = {"charge_id": self.ids.next("CHG", 8), "student_id": stu["id"],
                 "student_programme_id": sp["student_programme_id"], "term_id": term.term_id, "charge_type": kind,
                 "amount": amt, "charge_date": term.start, "due_date": due,
                 "currency_code": self.cfg["meta"]["currency_code"], "data_source": "SYNTHETIC"}
            stu["charges"].append(c)
            self.out["charges"].append(c)
        net = round(net, 2)
        if net <= 0:
            return
        r = stu["risk"]
        pw = self.fin["payer_behaviour_weights"]
        w = [max(pw["ON_TIME"] - 0.3 * r, 0.05), pw["LATE"] + 0.15 * r, pw["PARTIAL"] + 0.15 * r]
        kind = self.choice(["ON_TIME", "LATE", "PARTIAL"], w)
        plan = []
        if kind == "ON_TIME":
            k = int(rng.integers(1, 4))
            span = max((due - term.start).days + 9, 1)
            days = sorted(int(x) for x in rng.integers(0, span, size=k))
            for i, dd in enumerate(days):
                plan.append((term.start - timedelta(days=10) + timedelta(days=dd), net / k))
        elif kind == "LATE":
            plan.append((due + timedelta(days=int(rng.integers(5, 75))), net))
        else:
            frac = rng.uniform(0.3, 0.9)
            plan.append((due - timedelta(days=int(rng.integers(1, 10))), net * frac))
            if rng.random() < self.fin["partial_remainder_paid_probability"]:
                plan.append((due + timedelta(days=int(rng.integers(10, 150))), net * (1 - frac)))
        total = 0.0
        for i, (d, amt) in enumerate(plan):
            amt = round(net - total, 2) if (i == len(plan) - 1 and kind != "PARTIAL") else round(amt, 2)
            if kind == "PARTIAL" and i == len(plan) - 1 and len(plan) == 2:
                amt = round(net - total, 2)
            total += amt
            p = {"payment_id": "", "student_id": stu["id"], "term_id": term.term_id, "payment_date": d,
                 "amount": amt, "method": self.choice(["CARD", "BANK_TRANSFER", "SPONSOR"], [0.55, 0.35, 0.10]),
                 "payment_type": "SCHEDULED", "data_source": "SYNTHETIC"}
            stu["payments"].append(p)

    def hold_active(self, stu, d: date) -> bool:
        iv = hold_intervals(stu["charges"], stu["payments"], self.check_dates[stu["id"]], d, self.fin["hold_threshold"])
        return hold_active_on(iv, d)

    def resolve_hold(self, stu, d: date) -> None:
        # Cancel later scheduled payments for earlier terms, then pay the whole past-due balance on d.
        stu["payments"] = [p for p in stu["payments"] if p["payment_date"] <= d]
        amt = past_due(stu["charges"], stu["payments"], d)
        if amt > 0:
            stu["payments"].append({"payment_id": "", "student_id": stu["id"], "term_id": "", "payment_date": d,
                                    "amount": round(amt, 2), "method": "CARD", "payment_type": "HOLD_RESOLUTION",
                                    "data_source": "SYNTHETIC"})

    # ------------------------------------------------------------------ transitions
    def maybe_readmit(self, stu, sp, st, last_term: Term | None, decision_term: Term, passed, earned, load,
                      dismissed=False) -> dict | None:
        kind = "DISMISSED" if dismissed else "WITHDRAWN"
        if self.rng.random() >= self.acad["readmission_probability"][kind] or last_term is None:
            return None
        base = decision_term.seq
        nxt = self.next_regular(base, int(self.rng.integers(2, 6)) if dismissed else int(self.rng.integers(1, 4)))
        if nxt is None or nxt > self.last_seq:
            return None
        recorded = sp["outcome_recorded_date"]
        entry = self.by_seq[nxt]
        if (entry.start - recorded).days < 30:
            nxt = self.next_regular(nxt)
            if nxt is None or nxt > self.last_seq:
                return None
            entry = self.by_seq[nxt]
        app = self.add_application(stu["applicant"], stu["id"], st["programme"], entry, "READMISSION", "ADMITTED", True,
                                   50 + 10 * stu["ability"] + self.rng.normal(0, 8), earliest=recorded)
        return {"programme": st["programme"], "entry": entry, "entry_type": "READMISSION",
                "prev_sp": sp["student_programme_id"], "credits_in": earned, "passed": passed,
                "path_start": st["path_start"], "application_id": app["application_id"], "study_load": load}

    def maybe_next_degree(self, stu, sp, level, grad_term: Term, load) -> dict | None:
        nxt_level = {"UNDERGRADUATE": "MASTERS", "MASTERS": "DOCTORATE"}.get(level)
        if not nxt_level or self.rng.random() >= self.cfg["admissions"]["next_degree_probability"][level]:
            return None
        seq = self.admissible_after(grad_term.seq, int(self.choice([1, 2, 3, 4], [0.5, 0.3, 0.1, 0.1])))
        if seq is None or seq > self.last_seq:
            return None
        entry = self.by_seq[seq]
        programme = self.pick_programme(nxt_level)
        app = self.add_application(stu["applicant"], stu["id"], programme, entry, "NEXT_DEGREE", "ADMITTED", True,
                                   60 + 12 * stu["ability"] + self.rng.normal(0, 8))
        return {"programme": programme, "entry": entry, "entry_type": "NEXT_DEGREE", "prev_sp": sp["student_programme_id"],
                "credits_in": 0, "passed": set(), "path_start": entry.start, "application_id": app["application_id"],
                "study_load": None}

    # ------------------------------------------------------------------ applicants who never enrolled
    def add_non_enrolling_applications(self):
        cfg, rng = self.cfg, self.rng
        firsts = [a for a in self.out["applications"] if a["application_type"] == "NEW"]
        n = int(round(len(firsts) * cfg["admissions"]["non_enrolling_applications_per_new_student"]))
        dw = cfg["admissions"]["non_enrolling_decision_weights"]
        term_by_id = {t.term_id: t for t in self.terms}
        for _ in range(n):
            template = firsts[int(rng.integers(len(firsts)))]
            entry = term_by_id[template["entry_term_id"]]
            decision = self.choice(list(dw), list(dw.values()))
            self._non_enrolled(entry, template["programme_id"], decision)
        # future intake pipeline: Spring 2027 (FUTURE term) applications, decided or pending as of today
        future = next(t for t in self.terms if t.seq == self.next_regular(self.last_seq))
        for _ in range(cfg["admissions"]["future_term_applications"]):
            level = self.choice(list(cfg["intake"]["level_weights"]), list(cfg["intake"]["level_weights"].values()))
            decision = self.choice(["PENDING", "ADMITTED", "REJECTED"], [0.6, 0.3, 0.1])
            self._non_enrolled(future, self.pick_programme(level), decision, future_term=True)

    def _non_enrolled(self, entry: Term, programme, decision, future_term=False):
        level = self.prog[programme]["level"]
        apl = self.ids.next("APL")
        self.out["applicants"].append({"applicant_id": apl, **self.new_person(level, entry), "data_source": "SYNTHETIC"})
        score = self.rng.normal(42 if decision == "REJECTED" else 56, 10)
        row = self.add_application(apl, "", programme, entry, "NEW", decision, False, score,
                                   today_cap=self.as_of if future_term else None)
        if future_term:
            if row["submitted_date"] > self.as_of:
                row["submitted_date"] = self.as_of - timedelta(days=int(self.rng.integers(1, 60)))
            if decision == "PENDING" or row["decision_date"] == "" or row["decision_date"] > self.as_of:
                row["decision"], row["decision_date"] = "PENDING", ""
            elif row["decision_date"] < row["submitted_date"]:
                row["decision_date"] = row["submitted_date"] + timedelta(days=1)
