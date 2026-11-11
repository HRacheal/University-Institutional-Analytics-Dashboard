# Data Warehouse

Centralised data integration for the dashboard: cleaning and transforming the UCI dataset, generating the synthetic institutional source systems, defining the institutional metrics, and validating everything.

| File | Purpose |
|---|---|
| `config/synthetic_config.toml` | **All** generation assumptions and the random seed. Every value is a placeholder. Edit it, then regenerate |
| `pipelines/common.py` | Paths, the UCI file fingerprint, deterministic CSV writing |
| `pipelines/uci_processing.py` | Raw UCI → `data/processed/uci/` (read-only on the raw file; no dates or programmes invented) |
| `pipelines/synthetic/reference.py` | Calendar, placeholder schools, programmes, courses, rules, fees, roles, servers |
| `pipelines/synthetic/rules.py` | Grade mapping, academic standing rule, past-due balance and hold rules |
| `pipelines/synthetic/simulate.py` | Term-by-term life of each synthetic student (Admissions, Registrar, Finance) |
| `pipelines/synthetic/it_systems.py` | Accounts, logins, servers, incidents, nightly sync log |
| `pipelines/synthetic/derive.py` | Append-only student status history (admitted, stopped out, returned, withdrawn, dismissed, changed programme, graduated) |
| `pipelines/synthetic/generate.py` | Orchestrates the run; stamps `source_system` + `generation_run_id` on every row; exports `data/synthetic/<department>/`, `schema/data_dictionary.csv` and `manifest.json` |
| `pipelines/schema.py` | Documented schema of every file (type, required, allowed values, description), UCI included; source of the data dictionary |
| `pipelines/metrics.py` | The single definition of retention membership and rates (first-year, Fall/Spring/Summer comparisons, institutional vs programme), graduation records and rates, time-to-degree, enrolment and performance aggregates |
| `pipelines/validation.py` | Schema, key, consistency, timeline, rule and metric checks using independent re-implementations; writes `data/synthetic/reports/` (10-section data-quality report + metric CSVs) |
| `tests/test_pipeline.py` | Fast pytest checks (small sample) |
| `tests/test_validator_mutations.py` | 31 deliberately introduced errors; each must be detected by its specific validator check |
| `pipelines/feature_engineering/` | Leakage-safe feature engineering: `student_panel.py` (student-term panel, every feature dated on/before the prediction point), `datasets.py` (task datasets + dataset cards with targets, prediction points and excluded columns) → `data/processed/modeling/{uci,synthetic}/` |
| `pipelines/model_training/` | `leakage.py` (automated leakage gates), `core.py` (pipelines, metrics, plots, saving, tracking), `supervised.py` (classification/regression), `survival.py` (Cox PH), `forecasting.py` (rolling-origin forecasts), `segmentation.py`, `run_all.py`, `reports.py` |
| `models/` | Saved models (`*.joblib`) with `*.meta.json`; synthetic models are labelled DEMONSTRATION_ONLY, UCI models RESEARCH_ONLY |
| `reports/` | `feature_engineering_report.md`, `model_training_report.md`, `model_comparison.md`, `forecasting_report.md` + `model_evaluation/`, `feature_analysis/`, `forecasting/` |
| `experiments/experiment_log.jsonl` | Simple experiment tracking (MLflow is not installed) |
| `tests/test_modeling.py` | Feature, leakage, split, training, metric, save/load and forecasting tests |

Run from this folder (PowerShell):
```powershell
python -m pipelines.uci_processing
python -m pipelines.synthetic.generate
python -m pipelines.validation          # add --skip-repro to skip the two reproducibility re-runs
python -m pytest -q                     # about 4-5 minutes (mutation tests regenerate a 300-student sample)
```

Modelling (after the data exist; UCI and synthetic data are never combined):
```powershell
python -m pipelines.feature_engineering.datasets   # about 2.5 minutes
# TRAINING RUNS ONLY IN THE PROJECT'S GOOGLE COLAB NOTEBOOK (never on the local Windows machine):
#   python -m pipelines.model_training.run_all --only <task> --skip-forecasting   -> outputs backed up to MyDrive/analytics_project_outputs/<task>/
# Locally: restore and verify the saved artifacts instead (inference only)
python -m pipelines.model_registry.import_colab_sets --source <downloaded Drive sets> --task <task>   # or: model_registry.restore --source <Drive outputs>
python -m pipelines.model_registry.audit           # reloads every model, re-predicts the test rows, checks saved metrics reproduce
python -m pipelines.model_training.reports         # writes the four Markdown reports from the saved results
python -m pytest tests/test_modeling.py -q            # fits small models: run in Colab, not locally
```
Every synthetic model and forecast is labelled: SYNTHETIC DEMONSTRATION DATA — NOT REAL UNIVERSITY PREDICTIONS.

Nightly synchronisation into PostgreSQL is not implemented yet. `sync_runs.csv` is the synthetic history that the future job's monitoring screens will display.
