"""Academic and finance rules used by the generator (all PLACEHOLDER demonstration rules).

The validation module re-implements these rules independently, so a bug here is detected
rather than copied.
"""
from __future__ import annotations

from datetime import date


def letter_for(score: float, letters: list[str], points: list[float], f_below: float) -> tuple[str, float]:
    """Map a continuous score to the nearest letter grade; below f_below is F."""
    if score < f_below:
        return "F", 0.0
    best = min((abs(score - p), i) for i, p in enumerate(points) if p > 0)[1]
    return letters[best], points[best]


def next_standing(prev: str | None, cgpa: float, term_gpa: float, min_gpa: float) -> tuple[str, str]:
    if cgpa >= min_gpa:
        return "GOOD", "CGPA_AT_OR_ABOVE_MIN"
    if prev in (None, "GOOD"):
        return "WARNING", "CGPA_BELOW_MIN"
    if prev == "WARNING":
        return "PROBATION", "CGPA_BELOW_MIN_AFTER_WARNING"
    # prev == PROBATION
    if term_gpa < min_gpa:
        return "DISMISSED", "CGPA_AND_TERM_GPA_BELOW_MIN_ON_PROBATION"
    return "PROBATION", "PROBATION_CONTINUED_TERM_GPA_AT_OR_ABOVE_MIN"


# ------------------------------------------------------------------ finance: past-due balance and holds
def past_due(charges: list[dict], payments: list[dict], d: date) -> float:
    """Charges whose due date is before d, minus all payments made on or before d."""
    due = sum(c["amount"] for c in charges if c["due_date"] < d)
    paid = sum(p["amount"] for p in payments if p["payment_date"] <= d)
    return round(due - paid, 2)


def hold_intervals(charges, payments, check_dates, upto: date, threshold: float) -> list[tuple]:
    """Holds are placed on a check date when past-due > threshold and released on the first
    payment date that brings past-due to <= threshold. Returns (placed, released|None, amount)."""
    checks = {c for c in check_dates if c <= upto}
    points = sorted(checks | {p["payment_date"] for p in payments if p["payment_date"] <= upto})
    out, placed, amount = [], None, 0.0
    for d in points:
        bal = past_due(charges, payments, d)
        if placed is None and d in checks and bal > threshold:
            placed, amount = d, bal
        elif placed is not None and bal <= threshold:
            out.append((placed, d, amount))
            placed = None
    if placed is not None:
        out.append((placed, None, amount))
    return out


def hold_active_on(intervals: list[tuple], d: date) -> bool:
    return any(p <= d and (r is None or r > d) for p, r, _ in intervals)
