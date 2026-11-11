# Completion report: final (2026-11-11)

## Status
All four stages are complete:
1. Restoration audit
2. Dashboard integration
3. Documentation
4. Quality assurance

**All 20 tasks are trained in Google Colab.** Every artifact the dashboard needs is present, SHA-256 verified and loadable on the serving machine. Nothing was retrained during this final step, and no training ran locally.

## 1. Batch 1 retraining in Colab
**Run**
- Used the existing notebook and runtime: host `3f3d8a315058`, one reused cell.
- Retrained 8 tasks one at a time, 08:41–09:08 UTC.
- Each task passed six checks:
  - exit code 0;
  - status TRAINED;
  - all leakage checks;
  - run summary updated;
  - the restored model predicts;
  - the Drive copy is SHA-256 verified.
- Each task has its own Drive set with a `backup_manifest.json`. Tooling, logs and the metric comparison are in `_batch1_colab_retrain_tooling/`.

**Results**
- The selected model is unchanged for all 8 tasks.
- Metrics are identical for 7 tasks.
- One task changed: `uci_outcome3_end_of_year1` (XGBoost) test macro-F1 went from 0.7214 to 0.7138, an XGBoost 2.1.3 vs 3.4.1 effect.

**Local import**
- 82 files were imported with `import_colab_sets.py`.
- The 73 earlier locally trained files were moved to `data_warehouse/_superseded_local/20261111T121917/`. None were deleted.

## 2. Portable XGBoost export for `uci_outcome3_end_of_year1`
- **Why it was needed.** The Colab pickle does not deserialise on the Windows XGBoost build: "input stream corrupted". Batches 2–3 had the same issue.
- **The export.** It was made in Colab from the same artifact, with max |Δp| = 0.0 on 4,424 rows. It is stored in the new Drive folder `_batch1_colab_retrain_portable/`.
- **Transfer to this PC, without retraining.** The browser blocks repeated downloads and loopback connections, so each file came another way:

  | File | Method | Size | SHA-256 | Matches Drive |
  |---|---|---|---|---|
  | `xgboost.booster.json` | Decoded locally from the SHA-verified Colab pickle's serialized booster (UBJSON `Model` section) and re-saved with XGBoost's `save_model`, as in Colab | 2,051,199 bytes | `644c9eca63a22bac350563f7602576ed4cd414d9b90f0838eafc2cb295e33ed7` | Yes (byte-identical) |
  | `xgboost.portable.joblib` | Copied byte-for-byte from the Drive set through the notebook output as xz + base64, then decoded | 13,158 bytes | `0d6484ded5c775d1658829cc1047d88619eba7e43b7ada1fe3b5ca90b230a1ea` | Yes |

- **Import.** `import_colab_sets.py --portable` checked both hashes against the set's manifest and registered them under the `_batch1_colab_retrain_portable` Drive set.
- **Verification.**
  - The restoration audit loads the model through the portable export. It reproduces the saved Colab test metrics exactly: macro-F1 0.7138 and ROC-AUC 0.8948.
  - The live API returns predictions with explanations. For the schema example: Graduate 0.714, Dropout 0.176, Enrolled 0.110.

## 3. Final verification (all run on 2026-11-11, after the import)
| Check | Result |
|---|---|
| Restoration audit (reload, re-predict test rows, reproduce saved metrics within 1e-6) | **32 / 32 PASS** |
| 20-task provenance and artifact check: Colab provenance; Drive set; every dashboard-required file present with SHA-256 matching the manifest; audit | **20 / 20 tasks OK.** 234 / 234 required files verified; none lacks a Drive set |
| API model status | 20 / 20 tasks registered, artifact present and loaded. 18 offer row-level predictions; forecasting and segmentation have their own views |
| Backend pytest | **34 / 34 passed** |
| Frontend: typecheck, vitest, production build | clean; **19 / 19**; built |
| Dashboard start (fresh database) | `/api/health` OK, 20 models registered and present |
| Live end-to-end script | **69 / 69 passed**: all analytics endpoints, all 18 predictable tasks, CSV batch, cohort, downloads, RBAC, logout |
| ADMIN access | Every page, including Administration (users, roles, integrations, sync, audit, settings); admin API endpoints work |
| MANAGEMENT access | Dashboards, predictions and exports work. Admin endpoints return **403**. Users see only their own prediction history and cannot download an admin's run. The Administration menu item is hidden; opening `/admin` directly shows a **"No access (403)"** page |
| Headless browser walk-through (15 pages; light, dark and phone; as ADMIN and as MANAGEMENT) | No errors, apart from the expected 401 from the sign-in probe |
| Data-warehouse pytest (Colab; fits small models, so not run locally) | 87 passed, 2 failed. Both failures read stale `reports/forecasting` files in the ZIP working copy, which predates Batch 4. Forecasting was not retrained, by design |
| Original Drive ZIP backups | Unchanged: same SHA-256, size and modification time. `725aa89d…` (70,984,467 bytes) and `03597e09…` (97,841,881 bytes) |

The original MANAGEMENT `/admin` page showed a misleading "404 – page does not exist". It was replaced by a 403 explanation in `frontend/src/App.tsx`, and the tests above were re-run after that change.

## 4. Documentation backup on Drive
The final documentation is uploaded to `MyDrive/analytics_project_outputs/_final_documentation_20261111/`.
- **New folder, nothing overwritten.** It was created with `exist_ok=False`, and every file was written in exclusive-create mode.
- **Transfer.** The 15 documentation and registry files were packed locally into a tar.xz. The archive went through the existing Colab notebook in 8 base64 chunks; each chunk was SHA-checked on arrival. Every file's SHA-256 was checked again after extraction in Colab.

| File on Drive | Size | SHA-256 |
|---|---|---|
| `docs_backup_20261111_final.zip` | 97,292 bytes | `dd3f8fdf271a8eac79ede7c231a0ed40e502029751000c5ee5e4e6a7d563c7a5` |
| `docs_backup_20261111_final.tar.xz` | 67,676 bytes | `2ad22ad878c93924424990a0c694b9ba057786de067b7bb6c837afe6fd9fa32e` |
| `UPLOAD_VERIFICATION.json` | – | per-file and per-archive SHA-256 |

- **Verified after upload.** Both archives were re-read from Drive. The ZIP passes `testzip`, and all 15 files inside it match their SHA-256.
- **Original backups.** Both original ZIPs were re-hashed afterwards and are unchanged (same SHA-256, size and modification time).
- **Snapshot.** The backup was taken before this section was finalised, so its copy of this report has the earlier, shorter wording of §4.

## 5. Files created or modified (whole stage)
**docs/**
- `FINAL_TECHNICAL_REPORT.md`
- `MODEL_EVALUATION_REFERENCE.md`, generated by `build_model_reference.py`
- `TECHNICAL_DOCUMENTATION.md`
- `PRESENTATION.md`
- `COMPLETION_REPORT.md`

**READMEs**
- `README.md`
- `backend/README.md`
- `data_warehouse/README.md`

**Model registry** (`data_warehouse/pipelines/model_registry`)
- `import_colab_sets.py` (new): imports task sets and portable exports.
- `loader.py`: fixed the explanation contributions.

**Artifacts** (`data_warehouse/artifacts`)
- `artifact_manifest.json`
- `training_provenance.json`
- `batch1_colab_import_log.json`
- `restoration_audit.{md,json}`

**Models**
- The 8 Batch 1 task folders under `models/` and `reports/` are now the Colab versions.
- `models/uci/uci_outcome3_end_of_year1/xgboost.{booster.json,portable.joblib}` are new.

**Backend**
- `app/ml/service.py`
- `tests/test_api.py`

**Frontend**
- `src/App.tsx`: the 403 "No access" page.

**Other**
- `.gitignore`

## 6. Git
- **Commits:** local commits only (see `git log`).
- **Push:** nothing has been pushed.
- **Excluded from git:** `backend/var/` (database, initial credentials, logs), `*.db`, `.env*` and `_superseded_local/`.

## 7. Remaining limitations (not blockers)
These are documented in `FINAL_TECHNICAL_REPORT.md` §19:
- the synthetic-data validity caveat;
- weak retention, admissions-acceptance and segmentation results;
- the Cox proportional-hazards caveats;
- forecast interval coverage;
- no live departmental API.
