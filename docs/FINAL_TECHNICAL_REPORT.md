# University Institutional Analytics Dashboard: final technical report

Date: 2026-11-11.

**Sources.** Every number below comes from saved evaluation outputs:
- `data_warehouse/reports/**/results.json`;
- the artifact manifest;
- the restoration audit.

The full per-model tables are in [`MODEL_EVALUATION_REFERENCE.md`](MODEL_EVALUATION_REFERENCE.md). Operational detail is in [`TECHNICAL_DOCUMENTATION.md`](TECHNICAL_DOCUMENTATION.md).

> **Data honesty.** The institutional dashboards and the 16 institutional models use **synthetic demonstration data**. Their metrics show that the pipeline works, not that the models would predict real students. The 4 UCI models are benchmarks on a public Portuguese dataset and cannot be transferred to another institution.

---

## 1. Executive summary

The project delivers a working institutional analytics platform:

| Component | What it does |
|---|---|
| Data warehouse | UCI processing, a validated synthetic generator for 5,000 students, metric definitions, leakage-safe feature engineering |
| Model pipeline | **20 registered tasks**, all trained in Google Colab and backed up to Google Drive with SHA-256 manifests |
| Backend (FastAPI) | Role-based access control, audit logging, analytics, inference-only prediction services, departmental integrations |
| Frontend (Refine + Ant Design) | 13 dashboard and administration pages |

**Key verified facts:**

- **Training location.**
  - All 20 tasks were trained in Google Colab.
  - Eight Batch 1 tasks were first trained on the local Windows machine. They were **retrained in the project's single Colab notebook on 2026-11-11** with the unchanged methodology, and all 8 passed six automated checks.
  - Selected models are unchanged for all 8. Metrics reproduce exactly for 7 of them.
  - The exception is `uci_outcome3_end_of_year1`, which uses XGBoost: test macro-F1 changed from 0.7214 to 0.7138. The XGBoost version differs (2.1.3 locally vs 3.4.1 in Colab).
- **Restoration audit** (local, inference only): **32 of 32 artifacts PASS**. Every model reloads, predicts its held-out test rows and reproduces its saved metrics within 1e-6.
  - The Colab XGBoost pickle for `uci_outcome3_end_of_year1` does not deserialise on the Windows XGBoost build. It is served through its portable export (booster JSON plus sklearn wrapper), made in Colab from the same artifact (max |Δp| = 0.0 on 4,424 rows).
  - Both export files on this PC match the Drive copies by SHA-256 (§18).
- **Tests:**
  - Backend: 34 of 34 pass.
  - Frontend: 19 of 19 pass; typecheck and build are clean.
  - Live end-to-end: 69 of 69 checks pass, covering all 18 row-predictable tasks and both roles.
  - Data-warehouse tests in Colab: 87 passed, 2 failed. Both failures are stale forecasting outputs in the working copy (§18).
- **Strongest results:**
  - Next-term academic risk: ROC-AUC 0.985.
  - UCI dropout at the end of year 1: ROC-AUC 0.933.
  - Enrolment-headcount forecasts: WAPE 0.022–0.095.
- **Weakest results:**
  - Retention models: ROC-AUC about 0.62–0.68.
  - Admissions acceptance: ROC-AUC 0.631.
  - Segmentation: silhouette 0.190, which is weak cluster structure.

## 2. Project background and problem statement
Universities need a single place to monitor enrolment, academic performance, retention, graduation, admissions, finance and IT operations, and to anticipate academic risk early enough to act.

The obstacles:
- Departmental data are siloed (Admissions, Registrar, Finance, IT).
- Metric definitions differ between offices.
- Predictive tools are often opaque, or trained with leakage.

No real university data were available. So the project had to show an end-to-end, auditable system, using public data where it exists and clearly labelled synthetic data elsewhere.

## 3. Project objectives
1. Integrate departmental data behind one definition of each institutional metric (`pipelines/metrics.py`).
2. Provide dashboards for enrolment, performance, retention (Fall→Fall, Spring→Spring, Summer→Summer), graduation, admissions, finance and IT. All should have filters and exports.
3. Train, evaluate and serve predictive models for academic risk, retention, graduation, admissions, forecasting and segmentation, without data leakage.
4. Enforce role-based access (ADMIN, MANAGEMENT), auditing and privacy-preserving outputs.
5. Make every result reproducible and recoverable: per-task Drive backups with SHA-256 checks, and a restoration audit.

## 4. System requirements
| Area | Requirement (as implemented) |
|---|---|
| Functional | Sign-in with forced password change; nine filters; three term-to-term retention comparisons; single, CSV-batch and cohort predictions with explanations; forecast and segmentation views; prediction history; reports and CSV exports; user, role, integration, sync and settings administration; audit log |
| Non-functional | Inference only on the server; SHA-256-verified artifacts; responsive UI down to 390 px; light and dark themes; chart and table views of every figure; clear 403, 422 and 503 messages |
| Software | Python 3.12 (local inference), Node.js (frontend build; 25.5.0 on this machine), SQLite by default (PostgreSQL via `UIAD_DATABASE_URL`). Training: Google Colab, Python 3.13.18, scikit-learn 1.6.1, XGBoost 3.4.1, LightGBM 4.6.0, CatBoost 1.2.10, statsmodels 0.15.0 |
| Hardware | Any machine that can run the API locally. Training needs the Colab runtime (12 GB RAM); peak use was 757 MB per task |

## 5. Data sources and dataset descriptions
| Source | Size | Use |
|---|---|---|
| UCI *Predict Students' Dropout and Academic Success* (Realinho et al., 2021; CC BY 4.0) | 4,424 students × 37 columns; Graduate 49.9 %, Dropout 32.1 %, Enrolled 17.9 % | Four benchmark models only. Never mixed with synthetic data |
| Synthetic institutional data (generator 1.1.0, seed in `synthetic_config.toml`) | 5,000 students, 2016FA–2026FA; 31,965 term enrolments; 112,408 course enrolments; 13,600 applications; 116,157 charge lines; 134,387 login events; 720 sync runs | Every dashboard and 16 models |

- **Validation:** the synthetic data pass **476 of 476 validation checks**. Planted-error (mutation) tests additionally require each deliberately introduced error to be detected.
- **Placeholders:** all schools, programmes, fees and rules are placeholders.

## 6. Data preprocessing and feature engineering
- **UCI:**
  - The raw file is read-only and its SHA-256 is checked.
  - Columns are renamed (the misspelled `Nacionality` and the trailing-tab column are fixed only in processed copies).
  - Two datasets are built: **at enrolment** (application-time attributes) and **at the end of year 1** (adds semester 1–2 units and grades).
- **Synthetic:**
  - A student-term panel (`feature_engineering/student_panel.py`). Every feature is dated on or before the prediction point.
  - Features include cumulative and term GPA, course-completion and progression rates, standing history (warning and probation terms), gap terms, transfer credits, scholarship %, financial behaviour (payment completion, late-payment terms, balance) and the online share.
  - Task datasets with **dataset cards** (`data/processed/modeling/*/*.card.json`). Each card records the target definition, prediction point, row filter and **excluded leakage columns**.
- **Automated leakage gates** (`model_training/leakage.py`, checks L1–L6) must all pass before a task is trained:
  - target not among the features;
  - excluded columns absent;
  - no forbidden name patterns;
  - zone purity;
  - feature dates before the prediction point;
  - no in-progress or future terms.
- **Preprocessing inside each model pipeline:** median imputation and standardisation for numeric features, and one-hot encoding for categorical features. This is fitted on training folds only.

## 7. System architecture
```
Departmental sources ─► Data warehouse ─────────────────────────► Backend (FastAPI) ─────────► Frontend (Refine/React)
(sample | CSV | REST)   UCI processing · synthetic generator         integrations (active source)   13 pages, RBAC-aware menu
                        metrics.py · feature engineering             analytics · ml (inference)      charts + tables + CSV
                        model_training ──(Google Colab only)──►      model_registry (SHA-256)        model-output panels
                        Drive: analytics_project_outputs/<task>/ ─►  artifacts/artifact_manifest.json
```

| Layer | Responsibility |
|---|---|
| Data warehouse | Produces data and features. Model training runs only in Colab |
| Model registry | Loads artifacts lazily and verifies them against the manifest |
| Backend | Never trains. Enforces permissions on every endpoint and audits sensitive actions |

Details: `TECHNICAL_DOCUMENTATION.md` §1.

## 8. Model development methodology
- **Tasks:** 20 tasks across academic risk, retention, graduation, admissions, forecasting and segmentation. Task specifications are in `model_training/supervised.py`, `survival.py`, `forecasting.py` and `segmentation.py`.
- **Candidates for each supervised task:**
  - a majority (or mean) baseline;
  - logistic or ridge regression (the linear baseline);
  - random forest;
  - XGBoost;
  - LightGBM;
  - CatBoost.
- **Survival:** Cox proportional hazards (statsmodels PHReg), stratified by level, with standardised covariates.
- **Forecasting:**
  - Methods: seasonal-naive, ETS, ARIMA, SARIMA and XGBoost on lags.
  - The method for each series family is selected by rolling-origin backtest WAPE.
- **Segmentation:**
  - k-means, with k chosen by silhouette over k = 2–8 and cross-checked against Ward clustering.
  - An isolation forest (2 % contamination) for anomaly flags.

## 9. Training and validation methodology
- **Split:**
  - A student-grouped holdout: 25 % of students (StratifiedGroupKFold, seed 20261110) form the untouched test set.
  - 5-fold StratifiedGroupKFold cross-validation on the training students.
  - No student appears in both train and test.
- **Selection:** by the cross-validation metric only. The test set is used once, for reporting.
- **Robustness:** an out-of-time check. Students labelled before 2022-07-01 are used for training; those with a prediction date on or after that date are used for testing.
- **Thresholds:**
  - **Original threshold** (binary tasks): maximises class-1 F1 on the cross-validation out-of-fold predictions.
  - **Supplementary class-0 threshold:** added in Batch 2, and now also produced for the Batch 1 Colab retrains. It is reported separately and never replaces the original.
- **Training environment:**
  - Every task ran in the project's single Google Colab notebook (`run_all --only <task>`) and was backed up to `MyDrive/analytics_project_outputs/<task>/` with a `backup_manifest.json`.
  - The 2026-11-11 Batch 1 retrain checked six conditions for each task: exit code 0; status TRAINED; all leakage checks passed; run summary updated; restored model predicts finite outputs; Drive copy SHA-verified.

## 10. Evaluation metrics and justification
| Task type | Metric | Why |
|---|---|---|
| Binary, imbalanced (dropout, risk) | **PR-AUC** (selection), ROC-AUC, F1 / precision / recall at the threshold, Brier score | PR-AUC reflects performance on the rare adverse class. Brier measures calibration |
| Multiclass (UCI outcome) | **Macro-F1** (selection), one-vs-rest ROC-AUC, accuracy | Macro-F1 weighs the minority "Enrolled" class equally |
| Regression (next-term GPA) | **RMSE** (selection), MAE, R² | Error in GPA points. A persistence baseline is also reported |
| Survival | Concordance (Harrell's C), hazard ratios per SD with 95 % CI | Ranks time-to-event. Hazard ratios are interpretable effects |
| Forecasting | **WAPE** against seasonal-naive; empirical 80 % interval coverage | Scale-free error and an honest uncertainty check |
| Segmentation | Silhouette, Davies–Bouldin, k-means vs Ward adjusted Rand index | Internal validity and stability |

## 11. Results for all 20 registered tasks
Test-set results of the selected model:

| # | Task | Batch | Data | Selected | Test result |
|---|---|---|---|---|---|
| 1 | uci_dropout_enrolment_time | 1 | UCI | CatBoost | ROC-AUC 0.780 · PR-AUC 0.651 · F1 0.615 |
| 2 | uci_outcome3_enrolment_time | 1 | UCI | CatBoost | macro-F1 0.561 · ROC-AUC 0.757 |
| 3 | uci_dropout_end_of_year1 | 1 | UCI | Logistic | ROC-AUC 0.933 · PR-AUC 0.893 · F1 0.808 |
| 4 | uci_outcome3_end_of_year1 | 1 | UCI | XGBoost | macro-F1 0.714 · ROC-AUC 0.895 |
| 5 | syn_dropout_2y | 1 | SYN | Random forest | ROC-AUC 0.775 · PR-AUC 0.488 · F1 0.526 |
| 6 | syn_next_term_gpa | 1 | SYN | Random forest | RMSE 0.451 · R² 0.535 |
| 7 | syn_next_term_academic_risk | 1 | SYN | CatBoost | ROC-AUC 0.985 · PR-AUC 0.844 · F1 0.770 |
| 8 | syn_graduation_cox | 1 | SYN | Cox PH | concordance 0.730 |
| 9 | syn_dropout_cox | 1 | SYN | Cox PH | concordance 0.641 |
| 10 | syn_retention_fall_to_fall_institutional | 2 | SYN | Random forest | ROC-AUC 0.657 · PR-AUC 0.915 |
| 11 | syn_retention_fall_to_fall_programme | 2 | SYN | XGBoost | ROC-AUC 0.660 · PR-AUC 0.914 |
| 12 | syn_retention_spring_to_spring_institutional | 2 | SYN | Logistic | ROC-AUC 0.673 · PR-AUC 0.922 |
| 13 | syn_retention_spring_to_spring_programme | 2 | SYN | Logistic | ROC-AUC 0.677 · PR-AUC 0.919 |
| 14 | syn_retention_summer_to_summer_institutional | 2 | SYN | XGBoost | ROC-AUC 0.672 · PR-AUC 0.910 |
| 15 | syn_retention_summer_to_summer_programme | 2 | SYN | XGBoost | ROC-AUC 0.682 · PR-AUC 0.900 |
| 16 | syn_graduation_within_window | 3 | SYN | Random forest | ROC-AUC 0.824 · PR-AUC 0.840 · F1 0.823 |
| 17 | syn_admissions_offer | 3 | SYN | Logistic | ROC-AUC 0.723 · PR-AUC 0.815 |
| 18 | syn_admissions_accept | 3 | SYN | XGBoost | ROC-AUC 0.631 · PR-AUC 0.771 |
| 19 | forecasting | 4 | SYN | per series (§13) | WAPE 0.022–0.129 |
| 20 | syn_segmentation | 5 | SYN | k-means + isolation forest | silhouette 0.190 (weak) |

The retention PR-AUC values (about 0.91) look high because most students are retained: the base rate is about 0.88. Read ROC-AUC and the class-0 results in the reference document instead.

### Training provenance: 20-task verification
All 20 tasks were trained in Google Colab, and every task has a Drive backup set. Each task's meta.json records Python 3.13.18 and scikit-learn 1.6.1; forecasting has no meta.json because its methods are refitted at forecast time. `artifacts/training_provenance.json` records the evidence for each task.

| Batch | Tasks | Colab evidence | Drive set files |
|---|---|---|---|
| 1 (retrained 2026-11-11, runtime `3f3d8a315058`) | 8 previously local tasks | Retrain driver with six checks, all VERIFIED; logs in `_batch1_colab_retrain_tooling/` | 8–18 per task |
| 1 | syn_next_term_academic_risk | Colab cells, 2026-11-10 | 20 |
| 2 | 6 retention tasks | Batch 2 Colab driver | 19–22 |
| 3 | graduation within window, admissions offer and acceptance | Batch 3 Colab driver | 19–22 |
| 4 | forecasting | Batch 4 Colab cell | 25 |
| 5 | segmentation | Batch 5 Colab cell | 11 |

**Batch 1: local-trained vs Colab retrain**

| Task | Model | Local-trained | Colab retrain |
|---|---|---|---|
| uci_dropout_end_of_year1 | Logistic regression | ROC-AUC 0.9327 | 0.9327 |
| uci_outcome3_end_of_year1 | XGBoost | test macro-F1 0.7214, CV 0.7256 | **0.7138**, CV 0.7255 |
| uci_dropout_enrolment_time | CatBoost | ROC-AUC 0.7801 | 0.7801 |
| uci_outcome3_enrolment_time | CatBoost | macro-F1 0.5612 | 0.5612 |
| syn_dropout_2y | Random forest | PR-AUC 0.4881 | 0.4881 |
| syn_graduation_cox | Cox PH | concordance 0.7298 | 0.7298 |
| syn_dropout_cox | Cox PH | concordance 0.6406 | 0.6406 |
| syn_next_term_gpa | Random forest | RMSE 0.4506 | 0.4506 |

## 12. Model comparison and selection
- **Selection rule:** the highest cross-validation PR-AUC (binary), macro-F1 (multiclass) or lowest RMSE (regression).
- **Linear models are often equivalent.** For several tasks the gain over the linear baseline is within one CV standard deviation:
  - UCI end of year 1: logistic regression is itself the selected model.
  - The spring retention tasks.
  - Next-term GPA: random forest RMSE 0.4506 vs ridge 0.4506.
  - The reference flags each such case. The simpler model is a defensible alternative where interpretability matters.
- **Where boosted trees help:** the gains are largest on the synthetic risk and graduation tasks, where non-linear interactions (standing × GPA) exist by construction.

## 13. Forecasting results
| Series family | Method | WAPE | Seasonal-naive |
|---|---|---|---|
| Enrolment headcount, total | XGBoost on lags | 0.022 | 0.049 |
| Headcount by level / gender / load / mode / nationality | XGBoost on lags | 0.030–0.045 | 0.049–0.063 |
| Headcount by school / programme | XGBoost on lags | 0.052 / 0.095 | 0.056 / 0.097 |
| Applications / offers | ETS | 0.129 / 0.097 | 0.131 / 0.102 |
| Acceptances / new enrolments | Seasonal-naive | 0.084 | 0.084 |
| Course registrations | XGBoost on lags | 0.094 | 0.098 |

- **Interval coverage:** the empirical 80 % intervals are too narrow for ETS (coverage 0.70) and adequate for ARIMA (0.91). The dashboard shows intervals together with this caveat.
- **Early years:** headcount growth between 2016 and 2021 is a simulation warm-up artefact.

## 14. Segmentation and anomaly detection results
- **Clusters:**
  - Population: 1,721 currently enrolled students.
  - k = 4: silhouette 0.190, Davies–Bouldin 1.574, adjusted Rand index against Ward 0.526.
  - This is **weak structure**, so segments are descriptive groupings, not natural types.
- **Anomalies:** the isolation forest flagged 35 records (2 %). These are unusual records for **data-quality review**, never evidence of misconduct. Pseudonymous IDs are visible only with `student_level:read`.

## 15. Explainability and feature importance
- **Global importance:** TreeSHAP for tree models and coefficients for linear models.
  - Next-term risk: cumulative GPA, level, admission score, standing.
  - 2-year dropout: standing, admission score, cumulative GPA, warning terms.
  - Graduation within the window: progression rate, cumulative GPA, standing, study load.
  - UCI dropout at the end of year 1: semester 2 units approved, tuition fees up to date, semester 2 grade, semester 1 approved, age.
- **Per-record explanations:** shown in the Predictions page for 20 records or fewer, summed back to the original features.
  - A 2026-11-11 fix stopped multiclass and binary contributions from cancelling when averaged over classes.
- **Interpretation:** all importances are **associations, not causes**.

## 16. Fairness, privacy and ethical considerations
- **Fairness:**
  - Subgroup metrics by level are saved for every synthetic task.
  - Example (2-year dropout): undergraduate recall is **0.34**, against 0.68 for Master's and 0.57 for Doctorate. At the original threshold, the model would miss most undergraduate dropouts.
  - Recommendation: per-level thresholds or monitoring before any real use.
  - Gender and nationality subgroup results are not reported for synthetic tasks, because the generator assigned those attributes without outcome effects.
  - UCI models include gender and age as features. A real deployment would need a review of whether that is acceptable.
- **Privacy:**
  - The system holds no real student data.
  - Student-level outputs use pseudonymous IDs, are gated by `student_level:read`, and are audited.
  - Downloaded files carry data labels.
  - Passwords use scrypt; only token hashes are stored.
- **Ethics:**
  - Predictions are decision support for outreach, never automated decisions.
  - Every model panel states its data source and limitations.
  - Synthetic results are labelled DEMONSTRATION_ONLY.

## 17. Dashboard implementation
- **Pages:** Overview; Enrolment (nine filters, term comparison); Performance (attention list); Retention (three comparisons, institutional vs programme); Graduation; Admissions; Finance & IT; Forecasting; Predictions (single, CSV, cohort); Segmentation; Model evaluation; Prediction history; Reports; Administration (users, roles, integrations, sync runs, audit, settings).
- **Charts:** a CVD-validated palette, a table view and CSV download for every chart, and labelled status colours.
- **Model output** appears in visually separate panels.
- **Integrations:** each department has three connectors (sample, CSV import validated against the data dictionary, REST). No live departmental API is connected.

## 18. Testing and verification
| Suite | Where | Result |
|---|---|---|
| Backend API tests (`backend/tests`) | Local | **34 / 34 passed** |
| Frontend (vitest, typecheck, build) | Local | 19 / 19; typecheck and build clean |
| Live end-to-end (69 scripted checks against a running server) | Local | **69 / 69 passed.** Covers all 18 row-predictable tasks; ADMIN and MANAGEMENT access, including 403 on admin endpoints for MANAGEMENT |
| Headless UI walk-through (all pages; light, dark, phone) | Local | As ADMIN and as MANAGEMENT: no errors except the expected 401 on the login probe. MANAGEMENT sees a "No access (403)" page on Administration |
| Restoration audit (reload, re-predict test rows, reproduce saved metrics within 1e-6) | Local | **32 / 32 PASS** |
| Data-warehouse tests | Colab | **87 passed, 2 failed.** Both failures read `reports/forecasting` from the ZIP working copy, which predates the Batch 4 forecasting run. The current forecasting outputs are in the Drive set |
| Batch 1 retrain checks | Colab | 8 / 8 VERIFIED on all six checks |
| Original Drive ZIP backups | Colab | SHA-256, size and modification time unchanged before and after |

**Portable export for `uci_outcome3_end_of_year1`.** The export was made in Colab and stored on Drive in `_batch1_colab_retrain_portable/`. Its two files reached this PC without any retraining, and both match the Drive copies byte for byte:

| File | Size | SHA-256 | How it reached this PC |
|---|---|---|---|
| `xgboost.booster.json` | 2,051,199 bytes | `644c9eca…` | Re-created locally from the SHA-verified Colab pickle: its serialized booster was decoded and re-saved with XGBoost's own `save_model`, exactly as in Colab |
| `xgboost.portable.joblib` | 13,158 bytes | `0d6484de…` | Copied as compressed text through the notebook output |

Both files were then imported with `import_colab_sets --portable` and are registered in the manifest under that Drive set.

## 19. Limitations and threats to validity
- **Synthetic validity.** Relationships in the synthetic data were configured by the generator, so the models partly re-learn the generator's rules. Real-world performance is unknown.
- **UCI external validity.** The UCI data cover one Portuguese polytechnic. The "GPA" is an average of passed units only, and there are no dates.
- **Retention models are weak** (ROC-AUC about 0.66), because outcomes are dominated by the 88 % base rate.
- **Proportional hazards.** The assumption is questionable for several Cox covariates, so those hazard ratios are time-averaged. The baseline hazard is not saved, so only relative hazards are served.
- **Forecasting.** The intervals are too narrow for ETS, and the early series is a warm-up artefact.
- **Library versions.** Serving uses Python 3.12 / numpy 2.2.6, while training used Python 3.13 / numpy 2.4.6. The audit confirms that all metrics reproduce. The one XGBoost pickle that does not deserialise on Windows is served through its verified portable export.
- **Integrations.** No live departmental integration exists, and nightly synchronisation into PostgreSQL is not implemented.

## 20. Recommendations for future improvement
1. Replace the placeholders and synthetic data with verified institutional data, then retrain everything in Colab and re-audit before any use.
2. Add per-level threshold calibration and fairness monitoring. Run subgroup audits on real protected attributes, under governance.
3. Save Cox baseline hazards to provide absolute survival curves. Use conformal intervals for forecasts.
4. Export XGBoost models in the portable format at training time, to avoid cross-platform pickle issues.
5. Implement the REST connectors against real departmental APIs, add a scheduled sync, and move to PostgreSQL behind HTTPS.
6. Add model monitoring (drift, calibration) and scheduled retraining in Colab or another managed environment.

## 21. Conclusion
The project meets its objectives as a demonstration system:
- integrated, consistently defined institutional metrics;
- leakage-gated, reproducible models with a single, verified training provenance (Google Colab, Drive-backed);
- a secure, role-aware dashboard that separates recorded figures from model output and states every limitation.

The results are honest about weakness (retention, admissions acceptance, segmentation). All 32 saved models reload and reproduce their evaluation on the serving machine.

## 22. References
- Realinho, V., Vieira Martins, M., Machado, J., & Baptista, L. (2021). *Predict Students' Dropout and Academic Success* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5MC89 (CC BY 4.0).
- Pedregosa, F. et al. (2011). Scikit-learn: Machine Learning in Python. *JMLR* 12, 2825–2830.
- Chen, T., & Guestrin, C. (2016). XGBoost: A Scalable Tree Boosting System. *KDD '16*.
- Ke, G. et al. (2017). LightGBM: A Highly Efficient Gradient Boosting Decision Tree. *NeurIPS*.
- Prokhorenkova, L. et al. (2018). CatBoost: unbiased boosting with categorical features. *NeurIPS*.
- Lundberg, S. M., & Lee, S.-I. (2017). A Unified Approach to Interpreting Model Predictions. *NeurIPS*.
- Cox, D. R. (1972). Regression Models and Life-Tables. *JRSS B* 34(2), 187–220.
- Hyndman, R. J., & Athanasopoulos, G. (2021). *Forecasting: Principles and Practice* (3rd ed.). OTexts.
- Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008). Isolation Forest. *ICDM '08*.
- Rousseeuw, P. J. (1987). Silhouettes. *J. Comput. Appl. Math.* 20, 53–65.
- Saito, T., & Rehmsmeier, M. (2015). The Precision-Recall Plot Is More Informative than the ROC Plot When Evaluating Binary Classifiers on Imbalanced Datasets. *PLoS ONE* 10(3).
