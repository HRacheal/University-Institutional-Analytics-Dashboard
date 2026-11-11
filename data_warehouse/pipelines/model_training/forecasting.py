"""Term-level enrolment and admissions forecasting (Zone B synthetic) with rolling-origin backtests.

Important: a series has ONE observation per term. 31 terms of history (2016FA-2026FA census) is 31 observations however
many students are behind them. Series with too little history are marked REQUIRES_MORE_DATA and are not forecast.

Methods: seasonal naive (same season last year; baseline), ETS (additive damped trend + additive season on log1p),
ARIMA(1,1,0) on log1p, SARIMA(0,1,1)(0,1,1)[3] ("airline") on log1p, and one global XGBoost model with lag features
pooled across all eligible series (scale-free target: log change vs. the same season last year).
Prophet is NOT used: with 3 irregularly spaced terms per year and <= 31 points, its daily/weekly seasonality machinery
has nothing to work with and adds no justified value over SARIMA/ETS.
"""
from __future__ import annotations

import time
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.statespace.sarimax import SARIMAX

from ..feature_engineering.common import MODELING_DIR, SYN_BANNER, data_version
from . import core

warnings.filterwarnings("ignore")
P = 3                     # terms per academic year (Fall, Spring, Summer)
H = 3                     # forecast horizon: one academic year ahead
MIN_OBS = 18              # >= 6 full seasonal cycles from the first non-zero term
MIN_RECENT = 5            # every one of the last 9 terms must have at least 5 (log models and WAPE need non-trivial counts)
FIRST_ORIGIN = 18         # rolling origins: index 18 (2022SU) .. last-1
ALPHA = 0.2               # 80 % prediction intervals
STAT_METHODS = ["seasonal_naive", "ets", "arima", "sarima"]
ALL_METHODS = STAT_METHODS + ["xgboost_lags"]


# ------------------------------------------------------------------------------------------------ single-series methods
def _sn(y, h):
    n = len(y)
    return np.array([y[n - P + (k % P)] for k in range(h)], float), None, None


def _stat(method, y, h):
    z = pd.Series(np.log1p(np.asarray(y, float)))     # ETSModel.get_prediction needs pandas input
    if method == "ets":
        r = ETSModel(z, error="add", trend="add", damped_trend=True, seasonal="add", seasonal_periods=P).fit(disp=False, maxiter=2000)
        f = r.get_prediction(start=len(z), end=len(z) + h - 1).summary_frame(alpha=ALPHA)
        mean, lo, hi = f["mean"].values, f["pi_lower"].values, f["pi_upper"].values
    else:
        order, seas = ((1, 1, 0), (0, 0, 0, 0)) if method == "arima" else ((0, 1, 1), (0, 1, 1, P))
        r = SARIMAX(z, order=order, seasonal_order=seas, enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        f = r.get_forecast(h).summary_frame(alpha=ALPHA)
        mean, lo, hi = f["mean"].values, f["mean_ci_lower"].values, f["mean_ci_upper"].values
    return np.expm1(mean).clip(0), np.expm1(lo).clip(0), np.expm1(hi).clip(0)


FIT_FAILURES: list[dict] = []


def forecast_one(method, y, h=H, **context):
    """context (series, key, origin) is stored with any failure so every failed fit can be traced."""
    if method == "seasonal_naive":
        return _sn(y, h)
    try:
        f, lo, hi = _stat(method, y, h)
        f, lo, hi = np.asarray(f), np.asarray(lo), np.asarray(hi)
        if not np.isfinite(f).all():
            raise ValueError(f"non-finite forecast {f.tolist()}")
        return f, lo, hi
    except Exception as e:                       # recorded and reported; a failing method cannot be selected
        FIT_FAILURES.append({"method": method, **context, "n_obs": len(y), "error": repr(e)[:200]})
        return np.full(h, np.nan), None, None


# ------------------------------------------------------------------------------------------------ global XGBoost with lags
def _xgb_rows(z: np.ndarray, season0: int, upto: int, with_target=True):
    """Rows (origin t, horizon h) using values up to index t only. z = log1p(y). Target = z[t+h] - z[t+h-3]."""
    rows = []
    for t in range(P, upto + 1):
        for h in range(1, H + 1):
            if with_target and t + h > upto:
                continue
            b = z[t + h - P]
            feats = [z[t] - b, z[t - 1] - b, z[t - 2] - b, z[t - 3] - b, z[t] - z[t - P], h, (season0 + t + h) % P, b]
            rows.append((feats, (z[t + h] - b) if with_target else np.nan, t, h, b))
    return rows


def xgb_backtest_and_forecast(series: dict[str, np.ndarray], season0: int, origins: list[int]):
    from xgboost import XGBRegressor
    out = {}

    def fit(upto):
        X, y = [], []
        for z in series.values():
            for f, tgt, *_ in _xgb_rows(z, season0, upto):
                X.append(f); y.append(tgt)
        m = XGBRegressor(n_estimators=250, learning_rate=0.05, max_depth=3, subsample=0.9, min_child_weight=2,
                         random_state=core.SEED, n_jobs=4)
        return m.fit(np.array(X), np.array(y))
    for o in origins + [None]:
        last = (len(next(iter(series.values()))) - 1) if o is None else o
        m = fit(last)
        for k, z in series.items():
            b = np.array([z[last + h - P] for h in range(1, H + 1)])
            feats = [[z[last] - b[h - 1], z[last - 1] - b[h - 1], z[last - 2] - b[h - 1], z[last - 3] - b[h - 1], z[last] - z[last - P], h,
                      (season0 + last + h) % P, b[h - 1]] for h in range(1, H + 1)]
            out[(k, o)] = np.expm1(b + m.predict(np.array(feats))).clip(0)
    return out


# ------------------------------------------------------------------------------------------------ eligibility & backtest
def eligibility(y: np.ndarray) -> tuple[bool, str, int]:
    nz = np.nonzero(y)[0]
    if len(nz) == 0:
        return False, "all zero", 0
    n = len(y) - nz[0]
    if n < MIN_OBS:
        return False, f"only {n} terms since first non-zero value (< {MIN_OBS})", int(n)
    if y[-9:].min() < MIN_RECENT:
        return False, f"a recent term has fewer than {MIN_RECENT} (min of last 9 terms = {int(y[-9:].min())})", int(n)
    return True, "eligible", int(n)


def backtest(panel: pd.DataFrame, value_col: str, key_cols: list[str], label: str):
    """panel: one row per (key, term) ordered by term_sequence, complete grid."""
    panel = panel.sort_values(key_cols + ["term_sequence"])
    terms = panel.drop_duplicates("term_sequence").sort_values("term_sequence")
    term_ids = terms["term_id"].tolist()
    season0 = {"FALL": 0, "SPRING": 1, "SUMMER": 2}[terms["season"].iloc[0]]
    elig, series = [], {}
    for key, g in panel.groupby(key_cols, sort=False):
        y = g[value_col].to_numpy(float)
        ok, why, n = eligibility(y)
        k = key if isinstance(key, tuple) else (key,)
        elig.append({**dict(zip(key_cols, k)), "series": label, "terms_observed": len(y), "terms_since_first_nonzero": n,
                     "last_value": float(y[-1]), "mean_last_3": float(y[-3:].mean()), "status": "ELIGIBLE" if ok else "REQUIRES_MORE_DATA",
                     "reason": why})
        if ok:
            series["|".join(map(str, k))] = y
    n = len(term_ids)
    origins = list(range(FIRST_ORIGIN, n - 1))
    errs, finals = [], []
    xg = xgb_backtest_and_forecast({k: np.log1p(v) for k, v in series.items()}, season0, origins) if series else {}
    for key, y in series.items():
        for o in origins:
            for m in ALL_METHODS:
                if m == "xgboost_lags":
                    f, lo, hi = xg[(key, o)], None, None
                else:
                    f, lo, hi = forecast_one(m, y[: o + 1], series=label, key=key, origin=term_ids[o])
                for h in range(1, H + 1):
                    if o + h >= n:
                        continue
                    a = y[o + h]
                    errs.append({"series": label, "key": key, "method": m, "origin_term": term_ids[o], "target_term": term_ids[o + h],
                                 "horizon": h, "actual": a, "forecast": f[h - 1], "abs_error": abs(a - f[h - 1]),
                                 "in_80pi": (lo[h - 1] <= a <= hi[h - 1]) if lo is not None else np.nan})
        for m in ALL_METHODS:
            if m == "xgboost_lags":
                f, lo, hi = xg[(key, None)], None, None
            else:
                f, lo, hi = forecast_one(m, y, series=label, key=key, origin="final (full history)")
            for h in range(1, H + 1):
                finals.append({"series": label, "key": key, "method": m, "horizon": h, "forecast": f[h - 1],
                               "pi80_low": lo[h - 1] if lo is not None else np.nan, "pi80_high": hi[h - 1] if hi is not None else np.nan})
    return pd.DataFrame(elig), pd.DataFrame(errs), pd.DataFrame(finals), term_ids


def summarise(errs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    def agg(g):
        return pd.Series({"n_forecasts": len(g), "n_failed": int(g["forecast"].isna().sum()), "mae": g["abs_error"].mean(), "rmse": float(np.sqrt((g["abs_error"] ** 2).mean())),
                          "wape": g["abs_error"].sum() / max(g.loc[g["abs_error"].notna(), "actual"].abs().sum(), 1e-9),
                          "pi80_coverage": g["in_80pi"].astype(float).mean() if g["in_80pi"].notna().any() else np.nan})
    return errs.groupby(by).apply(agg, include_groups=False).reset_index()


def empirical_interval(errs: pd.DataFrame, finals: pd.DataFrame) -> pd.DataFrame:
    """For methods without a model-based interval: 10th/90th percentile of backtest log-ratio errors per (series, method, horizon)."""
    e = errs.assign(lr=np.log1p(errs["actual"]) - np.log1p(errs["forecast"]))
    q = e.groupby(["series", "method", "horizon"])["lr"].quantile([0.1, 0.9]).unstack()
    f = finals.copy()
    for i, r in f.iterrows():
        if np.isnan(r["pi80_low"]) and (r["series"], r["method"], r["horizon"]) in q.index:
            lo, hi = q.loc[(r["series"], r["method"], r["horizon"])]
            f.at[i, "pi80_low"] = max(np.expm1(np.log1p(r["forecast"]) + lo), 0)
            f.at[i, "pi80_high"] = np.expm1(np.log1p(r["forecast"]) + hi)
            f.at[i, "interval_type"] = "empirical (backtest errors)"
    f["interval_type"] = f.get("interval_type", pd.Series(index=f.index, dtype=object)).fillna("model-based")
    return f


# ------------------------------------------------------------------------------------------------ annual (academic-year / per-season) series
def annual_backtest(name: str, years: list[str], y: np.ndarray, first_origin: int = 5):
    rows, fin = [], []
    def fc(m, yy):
        if m == "naive":
            return yy[-1]
        if m == "drift":
            return yy[-1] + (yy[-1] - yy[0]) / (len(yy) - 1)
        try:
            r = ETSModel(pd.Series(np.log(yy)), error="add", trend="add", damped_trend=True).fit(disp=False)
            v = float(np.exp(np.asarray(r.forecast(1))[0]))
            if not np.isfinite(v):
                raise ValueError(f"non-finite forecast {v}")
            return v
        except Exception as e:                   # recorded and reported, like the term-level methods
            FIT_FAILURES.append({"method": "holt_damped(annual)", "series": name, "n_obs": len(yy), "error": repr(e)[:200]})
            return np.nan
    for o in range(first_origin, len(y) - 1):
        for m in ("naive", "drift", "holt_damped"):
            f = fc(m, y[: o + 1])
            rows.append({"series": name, "method": m, "origin": years[o], "target": years[o + 1], "actual": y[o + 1], "forecast": f,
                         "abs_error": abs(y[o + 1] - f)})
    for m in ("naive", "drift", "holt_damped"):
        fin.append({"series": name, "method": m, "forecast_next": fc(m, y)})
    return rows, fin


def _next_terms(last_term: str, k: int = H) -> list[str]:
    order = ["FA", "SP", "SU"]
    yr, s = int(last_term[:4]), last_term[4:]
    out = []
    for _ in range(k):
        i = order.index(s)
        if s == "FA":
            yr += 1
        s = order[(i + 1) % 3]
        out.append(f"{yr}{s}")
    return out


# ------------------------------------------------------------------------------------------------ main
def run_all() -> dict:
    t0 = time.time()
    FIT_FAILURES.clear()                         # one run = one failure log (the list is module-level)
    out = core.report_dir("forecasting")
    d = MODELING_DIR / "synthetic"
    enr = pd.read_csv(d / "ts_enrolment_by_term.csv")
    adm = pd.read_csv(d / "ts_admissions_by_term.csv")
    cdm = pd.read_csv(d / "ts_course_demand_by_programme.csv")
    ay = pd.read_csv(d / "ts_enrolment_by_academic_year.csv")
    results = {"label": SYN_BANNER, "data_version": data_version(), "settings": {"terms_per_year": P, "horizon_terms": H,
               "min_terms_since_first_nonzero": MIN_OBS, "min_recent_value": MIN_RECENT, "first_backtest_origin_index": FIRST_ORIGIN,
               "interval": "80 %", "prophet": "not used (see module docstring)"}}
    E, R, F = [], [], []
    # 1. enrolment headcount by term, each dimension
    for dim, g in enr.groupby("dimension", sort=False):
        el, er, fi, term_ids = backtest(g, "value", ["series_key"], f"enrolment_headcount:{dim}")
        el.insert(0, "dimension", dim); E.append(el); R.append(er); F.append(fi)
    results["enrolment_terms"] = term_ids
    results["n_term_observations"] = len(term_ids)
    # 2. admissions funnel by entry term (total and by programme)
    for col in ("applications", "offers", "acceptances", "new_enrolments"):
        el, er, fi, _ = backtest(adm, col, ["programme_id"], f"admissions_{col}")
        el.insert(0, "dimension", "programme_id"); E.append(el); R.append(er); F.append(fi)
    # 3. course demand (course registrations) by programme
    cg = cdm.pivot_table(index="programme_id", columns="term_sequence", values="course_registrations", fill_value=0).stack().rename("value").reset_index()
    tmap = enr.drop_duplicates("term_sequence").set_index("term_sequence")[["term_id", "season"]]
    cg = cg.join(tmap, on="term_sequence")
    el, er, fi, _ = backtest(cg, "value", ["programme_id"], "course_registrations")
    el.insert(0, "dimension", "programme_id"); E.append(el); R.append(er); F.append(fi)

    elig = pd.concat(E, ignore_index=True)
    errs = pd.concat(R, ignore_index=True)
    finals = empirical_interval(errs, pd.concat(F, ignore_index=True))
    nxt = _next_terms(term_ids[-1])
    finals["target_term"] = finals["horizon"].map(lambda h: nxt[h - 1])
    finals["target_term_note"] = finals["target_term"].map(lambda t: "beyond the configured calendar (ends 2027SU)" if t not in ("2027SP", "2027SU") else "")
    summ = summarise(errs, ["series", "method"])
    summ_h = summarise(errs, ["series", "method", "horizon"])
    per_series = summarise(errs, ["series", "key", "method"])
    # best method per series family = lowest pooled WAPE (all horizons)
    # never select a method that failed on any backtest origin, whose score is missing/non-finite, or whose final
    # (full-history) forecast failed for any series key
    final_bad = finals.groupby(["series", "method"])["forecast"].apply(lambda v: bool((~np.isfinite(v.astype(float))).any()))
    summ["final_forecast_failed"] = [bool(final_bad.get((a_, m_), True)) for a_, m_ in zip(summ["series"], summ["method"])]
    summ["eligible_for_selection"] = (summ["n_failed"] == 0) & np.isfinite(summ["wape"].astype(float)) & ~summ["final_forecast_failed"]
    ok = summ[summ["eligible_for_selection"]]
    no_valid = sorted(set(summ["series"]) - set(ok["series"]))
    if no_valid:
        raise RuntimeError(f"no forecasting method has a valid evaluation for series {no_valid}")
    best = ok.loc[ok.groupby("series")["wape"].idxmin(), ["series", "method", "wape"]].rename(columns={"method": "best_method", "wape": "best_wape"})
    sn = summ[summ["method"] == "seasonal_naive"][["series", "wape"]].rename(columns={"wape": "seasonal_naive_wape"})
    best = best.merge(sn, on="series")
    best["improvement_vs_seasonal_naive_pct_points"] = 100 * (best["seasonal_naive_wape"] - best["best_wape"])
    chosen = finals.merge(best[["series", "best_method"]], left_on=["series", "method"], right_on=["series", "best_method"])
    chosen = chosen.drop(columns="best_method")
    chosen.insert(0, "label", SYN_BANNER)
    # validation: the published (selected-method) forecasts must be finite and non-negative
    fv = chosen["forecast"].astype(float)
    bad_sel = chosen[~np.isfinite(fv) | (fv < 0)]
    if len(bad_sel):
        raise RuntimeError(f"{len(bad_sel)} selected forecasts are NaN/inf/negative: {bad_sel[['series', 'key', 'method']].head().to_dict('records')}")
    fa = finals["forecast"].astype(float)
    validation = {"selected_forecasts": int(len(chosen)), "selected_non_finite": 0, "selected_negative": 0,
                  "selected_interval_non_finite": int((~np.isfinite(chosen[["pi80_low", "pi80_high"]].astype(float))).any(axis=1).sum()),
                  "all_methods_forecasts": int(len(finals)),
                  "all_methods_non_finite_by_method": finals.assign(nf=~np.isfinite(fa)).groupby("method")["nf"].sum().astype(int).to_dict(),
                  "backtest_non_finite_by_method": errs.assign(nf=~np.isfinite(errs["forecast"].astype(float))).groupby("method")["nf"].sum().astype(int).to_dict(),
                  "note": "non-finite values exist only for methods that failed to fit; such methods are never selected"}

    # 4. conversion rates: rate forecasts from same-season history (rates are bounded; backtest in percentage points)
    rate_rows = []
    a = adm[adm["programme_id"] == "ALL"].sort_values("term_sequence").reset_index(drop=True)
    for rate in ("application_to_offer", "offer_to_acceptance", "acceptance_to_enrolment"):
        v = a[rate].to_numpy(float)
        for o in range(FIRST_ORIGIN, len(v) - 1):
            for h in range(1, H + 1):
                if o + h >= len(v):
                    continue
                same = [v[i] for i in range(o + h - P, -1, -P) if i <= o][:3]
                rate_rows.append({"rate": rate, "origin": a["term_id"][o], "target": a["term_id"][o + h], "horizon": h, "actual": v[o + h],
                                  "seasonal_naive": same[0], "mean_last3_same_season": float(np.mean(same))})
    rr = pd.DataFrame(rate_rows)
    rate_summary = rr.groupby("rate").apply(lambda g: pd.Series({
        "n": len(g), "mae_pp_seasonal_naive": 100 * (g["actual"] - g["seasonal_naive"]).abs().mean(),
        "mae_pp_mean_last3_same_season": 100 * (g["actual"] - g["mean_last3_same_season"]).abs().mean(),
        "min_observed": g["actual"].min(), "max_observed": g["actual"].max()}), include_groups=False).reset_index()
    rate_fc = []
    for rate in ("application_to_offer", "offer_to_acceptance", "acceptance_to_enrolment"):
        v = a[rate].to_numpy(float)
        for h, tt in enumerate(nxt, 1):
            same = [v[i] for i in range(len(v) - 1 + h - P, -1, -P)][:3]
            rate_fc.append({"label": SYN_BANNER, "rate": rate, "target_term": tt, "forecast_mean_last3_same_season": float(np.mean(same)),
                            "range_last3": f"{min(same):.3f}-{max(same):.3f}"})

    # 5. annual series: unduplicated academic-year headcount and per-season (Fall / Spring / Summer) yearly series
    ann_rows, ann_fin = [], []
    ayc = ay[ay["year_status"] == "COMPLETE"].sort_values("academic_year")
    r_, f_ = annual_backtest("academic_year_unduplicated_headcount", ayc["academic_year"].tolist(), ayc["unduplicated_headcount"].to_numpy(float))
    ann_rows += r_; ann_fin += f_
    tot = enr[enr["dimension"] == "TOTAL"]
    for season, g in tot.groupby("season"):
        g = g.sort_values("term_sequence")
        r_, f_ = annual_backtest(f"term_headcount_{season.lower()}_only", g["term_id"].tolist(), g["value"].to_numpy(float), first_origin=5)
        ann_rows += r_; ann_fin += f_
    ann = pd.DataFrame(ann_rows)
    ann_summary = ann.groupby(["series", "method"]).apply(lambda g: pd.Series({"n_forecasts": len(g), "n_failed": int(g["forecast"].isna().sum()),
                                                                             "mae": g["abs_error"].mean() if g["forecast"].notna().all() else np.nan,
                                                                             "wape": g["abs_error"].sum() / g["actual"].sum() if g["forecast"].notna().all() else np.nan}),
                                                         include_groups=False).reset_index()
    ann_obs = {"academic_year_unduplicated_headcount": int(len(ayc)), **{f"term_headcount_{s.lower()}_only": int((tot["season"] == s).sum())
                                                                        for s in ("FALL", "SPRING", "SUMMER")}}

    # 6. programme demand scenarios (demand only; capacity is not available)
    sc = chosen[chosen["series"].isin(["admissions_applications", "enrolment_headcount:programme_id", "course_registrations"])].copy()
    sc["scenario_low"] = sc["pi80_low"]; sc["scenario_baseline"] = sc["forecast"]; sc["scenario_high"] = sc["pi80_high"]
    sc["scenario_demand_minus_10pct"] = sc["forecast"] * 0.9; sc["scenario_demand_plus_10pct"] = sc["forecast"] * 1.1
    sc = sc[["label", "series", "key", "target_term", "method", "scenario_low", "scenario_baseline", "scenario_high",
             "scenario_demand_minus_10pct", "scenario_demand_plus_10pct", "interval_type"]]

    # ------------------------------------------------------------------ save
    elig.to_csv(out / "series_eligibility.csv", index=False)
    errs.to_csv(out / "backtest_errors.csv", index=False, float_format="%.4f")
    summ.to_csv(out / "backtest_summary_by_series_method.csv", index=False, float_format="%.4f")
    summ_h.to_csv(out / "backtest_summary_by_horizon.csv", index=False, float_format="%.4f")
    per_series.to_csv(out / "backtest_summary_per_series.csv", index=False, float_format="%.4f")
    best.to_csv(out / "best_method_by_series_family.csv", index=False, float_format="%.4f")
    finals.insert(0, "label", SYN_BANNER)
    finals.to_csv(out / "forecasts_all_methods.csv", index=False, float_format="%.2f")
    chosen.to_csv(out / "forecasts_selected_method.csv", index=False, float_format="%.2f")
    rr.to_csv(out / "conversion_rate_backtest.csv", index=False, float_format="%.4f")
    rate_summary.to_csv(out / "conversion_rate_backtest_summary.csv", index=False, float_format="%.4f")
    pd.DataFrame(rate_fc).to_csv(out / "conversion_rate_forecasts.csv", index=False, float_format="%.4f")
    ann_summary.to_csv(out / "annual_series_backtest_summary.csv", index=False, float_format="%.4f")
    pd.DataFrame(ann_fin).assign(label=SYN_BANNER).to_csv(out / "annual_series_forecasts.csv", index=False, float_format="%.1f")
    sc.to_csv(out / "programme_demand_scenarios.csv", index=False, float_format="%.1f")
    _plots(out, enr, adm, errs, finals, best, term_ids, nxt)
    ff = pd.DataFrame(FIT_FAILURES, columns=["method", "series", "key", "origin", "n_obs", "error"])
    ff.to_csv(out / "fit_failures.csv", index=False)
    excl = summ[~summ["eligible_for_selection"]]
    results["fit_failures"] = {"count": len(FIT_FAILURES), "file": "fit_failures.csv",
                               "by_method": ff.groupby("method").size().to_dict(),
                               "by_series_method": {f"{s}|{m}": int(n) for (s, m), n in ff.groupby(["series", "method"]).size().items()},
                               "distinct_errors": ff["error"].str.slice(0, 120).value_counts().head(10).to_dict(),
                               "methods_excluded_from_selection": [
                                   {"series": r_["series"], "method": r_["method"], "backtest_failures": int(r_["n_failed"]),
                                    "final_forecast_failed": bool(r_["final_forecast_failed"]), "wape_finite": bool(np.isfinite(float(r_["wape"])))}
                                   for _, r_ in excl.iterrows()],
                               "examples": FIT_FAILURES[:10]}
    results["validation"] = validation
    results.update({"eligibility_counts": elig.groupby(["series", "status"]).size().unstack(fill_value=0).to_dict("index"),
                    "best_method_by_series": best.to_dict("records"), "annual_observations": ann_obs,
                    "annual_summary": ann_summary.to_dict("records"), "conversion_rate_summary": rate_summary.to_dict("records"),
                    "next_terms": nxt, "seconds": round(time.time() - t0, 1)})
    core.write_json(results, out / "forecasting_results.json")
    core.log_experiment({"task_id": "forecasting", "zone": "SYNTHETIC", "best_method_by_series": best.to_dict("records"),
                         "seed": core.SEED, "data_version": results["data_version"]})
    return results


def _plots(out, enr, adm, errs, finals, best, term_ids, nxt):
    bm = dict(zip(best["series"], best["best_method"]))

    def panel(ax, label, key, y, title):
        x = np.arange(len(y))
        ax.plot(x, y, "k-o", ms=3, lw=1.2, label="actual")
        for m, st in (("seasonal_naive", ":"), (bm.get(label, "sarima"), "-")):
            e = errs[(errs["series"] == label) & (errs["key"] == key) & (errs["method"] == m) & (errs["horizon"] == 1)]
            if len(e):
                ax.plot([term_ids.index(t) for t in e["target_term"]], e["forecast"], st, lw=1.2, label=f"1-step backtest: {m}")
        f = finals[(finals["series"] == label) & (finals["key"] == key) & (finals["method"] == bm.get(label, "sarima"))]
        if len(f):
            xf = np.arange(len(y), len(y) + len(f))
            ax.plot(xf, f["forecast"], "r-o", ms=3, label=f"forecast ({bm.get(label)})")
            ax.fill_between(xf, f["pi80_low"], f["pi80_high"], color="r", alpha=0.15, label="80 % interval")
        labels = term_ids + nxt
        ax.set_xticks(range(0, len(labels), 3), labels[::3], rotation=60, fontsize=6)
        ax.set_title(title, fontsize=8); ax.legend(fontsize=5.5)
    tot = enr[(enr["dimension"] == "TOTAL")].sort_values("term_sequence")["value"].to_numpy(float)
    fig, ax = plt.subplots(figsize=(9, 4))
    panel(ax, "enrolment_headcount:TOTAL", "ALL", tot, "Total census headcount by term: actual, backtest and forecast")
    core._stamp(fig, "SYNTHETIC"); fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(out / "total_enrolment_forecast.png", dpi=110); plt.close(fig)
    for dim in ("level", "school_id", "delivery_mode", "gender"):
        g = enr[enr["dimension"] == dim]
        keys = [k for k in g["series_key"].unique() if ((errs["series"] == f"enrolment_headcount:{dim}") & (errs["key"] == str(k))).any()]
        if not keys:
            continue
        fig, axes = plt.subplots(1, len(keys), figsize=(4.2 * len(keys), 3.6), squeeze=False)
        for ax, k in zip(axes[0], keys):
            panel(ax, f"enrolment_headcount:{dim}", str(k), g[g["series_key"] == k].sort_values("term_sequence")["value"].to_numpy(float), f"{dim} = {k}")
        core._stamp(fig, "SYNTHETIC"); fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(out / f"enrolment_forecast_by_{dim}.png", dpi=100); plt.close(fig)
    a = adm[adm["programme_id"] == "ALL"].sort_values("term_sequence")
    fig, axes = plt.subplots(1, 4, figsize=(17, 3.6))
    for ax, col in zip(axes, ("applications", "offers", "acceptances", "new_enrolments")):
        panel(ax, f"admissions_{col}", "ALL", a[col].to_numpy(float), f"Admissions: {col}")
    core._stamp(fig, "SYNTHETIC"); fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(out / "admissions_funnel_forecast.png", dpi=100); plt.close(fig)


if __name__ == "__main__":
    r = run_all()
    print(r["best_method_by_series"])
