# SYNTHETIC DEMONSTRATION DATA: NOT REAL UNIVERSITY RECORDS

Every file in this folder was produced by `data_warehouse/pipelines/synthetic/generate.py`
(seed and settings in `manifest.json`). Every row has `data_source = SYNTHETIC`.
Reference rows (schools, programmes, calendar, rules, fees) are also `verification_status = PLACEHOLDER`.

* No synthetic person, programme, policy or calendar corresponds to a real university record.
* UCI students are NOT in this folder; they live separately in `data/processed/uci/`.
* Folders follow the institutional architecture: reference, admissions, registrar, finance, it, data_warehouse.
* Every row also carries `source_system` (the departmental system it represents) and `generation_run_id`
  (see `data_warehouse/generation_runs.csv`).
* `schema/data_dictionary.csv` documents every column (type, required, allowed values, description).
* `reports/` holds the data-quality report and validated metric outputs.
* Fall 2026 is IN PROGRESS (census snapshot only: no grades, standing or graduations). Spring/Summer 2027 are FUTURE.

Regenerate:  cd data_warehouse ; python -m pipelines.synthetic.generate
Validate:    cd data_warehouse ; python -m pipelines.validation
