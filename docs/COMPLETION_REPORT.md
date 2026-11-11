# Completion report (2026-11-11)

## Status in brief

| Stage | Status |
|---|---|
| 1. Restoration audit | **Done.** 31 / 32 artifacts PASS; the one exception is pending |
| 2. Dashboard integration | **Done** |
| 3. Documentation | **Done** |
| 4. Quality assurance | **Done**, except one item that needs the user |

**Model training standardised on Colab.** All 20 tasks now have Google Colab training provenance.

**Pending.** Two items need one action each from the user; see "Genuine blockers" at the end.

## Batch 1 retraining in Colab

**How it was run.**
- **Notebook and runtime:** the existing notebook and runtime were reused (one cell, host `3f3d8a315058`). No new notebook or runtime was created.
- **Working copy:** `University-Institutional-Analytics-Dashboard_latest.zip` was extracted read-only. The recorded patches were applied and checked against `final_code_sha256.json`.
- **Order:** the 8 tasks ran one at a time between 08:41 and 09:08 UTC.
- **Checks per task** (all 8 are **VERIFIED**):
  - exit code 0;
  - status TRAINED;
  - all leakage checks pass;
  - run summary updated;
  - the restored model predicts finite outputs;
  - the Drive copy is SHA-256 verified.
- **Drive storage:** one new set per task in `MyDrive/analytics_project_outputs/<task>/`, with `backup_manifest.json`. Tooling, logs and the metric comparison are in `_batch1_colab_retrain_tooling/` (15 files, SHA-256 verified).

**Results.**
- **Selected models:** unchanged for all 8 tasks.
- **Metrics:** identical for 7 tasks. For `uci_outcome3_end_of_year1` (XGBoost), test macro-F1 went from 0.7214 to 0.7138; this is an XGBoost 2.1.3 vs 3.4.1 effect.
- **New outputs:** the Colab run also produced the **supplementary** class-0 threshold outputs (Batch 2–5 methodology) for the Batch 1 binary tasks. The original thresholds are unchanged.

**Local copy.**
- **Download:** the Batch 1 sets only, as one bundle (SHA-256 `f722a992…`, matched).
- **Import:** `pipelines/model_registry/import_colab_sets.py` imported 82 files. The 73 earlier local-trained files were **moved** to `data_warehouse/_superseded_local/20261111T121917/`; none were deleted.
- **Manifest:** `artifacts/artifact_manifest.json` was updated for these 8 tasks only. The history entry is recorded and every file is linked to a Drive set.
- **Provenance:** `artifacts/training_provenance.json` covers all 20 tasks.

**Untouched.**
- No Batch 2–5 outputs were copied.
- Nothing was trained locally.
- **Original ZIPs:** both are unchanged, with the same SHA-256, size and modification time before and after:
  - `725aa89d…` (70,984,467 bytes)
  - `03597e09…` (97,841,881 bytes)

## Tests (all run on 2026-11-11 after the import)
| Suite | Result |
|---|---|
| Restoration audit (local, inference only) | 31 PASS, 1 FAIL_LOAD (`uci_outcome3_end_of_year1` XGBoost, see blockers) |
| Backend pytest | 33 passed, 1 failed (same task) |
| Frontend: typecheck, vitest | clean; 19 / 19 |
| Live end-to-end API script | 68 passed, 0 failed; that task correctly returns 503 with the reason |
| Headless UI walk-through (15 pages; light, dark and phone) | no errors except the expected 401 from the sign-in probe |
| Data-warehouse pytest (Colab) | 87 passed, 2 failed. Both failures are stale `reports/forecasting` files in the ZIP working copy, which predate Batch 4. The forecasting task was not retrained, by design |
| Secrets scan of the files to be committed | No credentials, keys or tokens. `backend/var/`, `.env*` and `*.db` are git-ignored |

## Files created or modified in this stage
- **docs/:** `FINAL_TECHNICAL_REPORT.md`, `MODEL_EVALUATION_REFERENCE.md` (with its generator `build_model_reference.py`), `TECHNICAL_DOCUMENTATION.md`, `PRESENTATION.md` and `COMPLETION_REPORT.md`.
- **README files:** root `README.md`, `backend/README.md` and `data_warehouse/README.md`, which now states that training runs in Colab only.
- **data_warehouse/pipelines/model_registry:**
  - `import_colab_sets.py` (new);
  - `loader.py`: explanation fix, so that class contributions no longer cancel.
- **data_warehouse/artifacts:**
  - `artifact_manifest.json`, `training_provenance.json` and `batch1_colab_import_log.json`;
  - `restoration_audit.{md,json}`.
- **Backend:**
  - `backend/app/ml/service.py`: Cox example inputs set to the training means;
  - `backend/tests/test_api.py`: 2 new tests, 1 test rewritten.
- **Models and reports:** the 8 Batch 1 task folders under `data_warehouse/models` and `reports`, replaced by the Colab versions.
- **`.gitignore`:** now covers `backend/var/`, `*.db` and `_superseded_local/`.

## Genuine blockers (need you)
1. **Portable export for `uci_outcome3_end_of_year1`.**
   - **Problem:** the Colab XGBoost pickle does not load on the Windows XGBoost build. This is the same issue as Batch 2–3, which was solved the same way.
   - **Done in Colab:** a portable export was made and verified identical (max |Δp| = 0.0 on 4,424 rows). It is saved to the new Drive folder `analytics_project_outputs/_batch1_colab_retrain_portable/`.
   - **Problem:** the browser blocked the second automatic download.
   - **What you need to do:** allow multiple downloads for colab.research.google.com, or download that Drive folder manually. Then run, from `data_warehouse/`:
     ```
     ..\.venv\Scripts\python -m pipelines.model_registry.import_colab_sets --portable --source <folder>
     ..\.venv\Scripts\python -m pipelines.model_registry.audit
     ```
   - **Expected result:** 32 / 32 PASS. Until then, the dashboard reports this one model as unavailable.
2. **Drive backup of the new documents.**
   - **Problem:** files cannot be uploaded from this PC to Drive automatically.
   - **Prepared:** `docs_backup_20261111.zip` is in your Downloads folder.
   - **What you need to do:** upload it to `MyDrive/analytics_project_outputs/_final_documentation_20261111/` (a new folder). Do not replace either original ZIP.
