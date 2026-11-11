import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearMe } from "../auth";
import HistoryPage from "../pages/History";
import SegmentationPage from "../pages/Segmentation";
import { MGMT_ME, mockFetch, wrap } from "./helpers";

beforeEach(() => clearMe());

describe("pages", () => {
  it("prediction history lists runs with band summaries", async () => {
    mockFetch({ "/api/auth/me": MGMT_ME, "/api/predictions": { runs: [
      { id: 7, ts: "2026-11-11T10:00:00", username: "mgr", task: "syn_dropout_2y", model: "random_forest", mode: "cohort", n_rows: 1849,
        input_name: "current cohort", summary: { bands: { HIGH: 109, ELEVATED: 1020, LOW: 720 } }, result_file: "run_7.csv" }] } });
    render(wrap(<HistoryPage />));
    expect(await screen.findByText("syn_dropout_2y")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("109")).toBeInTheDocument();
    expect(await screen.findByLabelText("Download run 7")).toBeInTheDocument();
  });

  it("segmentation states weak structure and that anomalies are not misconduct", async () => {
    mockFetch({ "/api/auth/me": { ...MGMT_ME, permissions: ["analytics:read"] }, "/api/segmentation": {
      label: "SYNTHETIC", n_students: 10, segment_sizes: { 0: 6, 1: 4 }, anomalies_by_segment: { 0: 0, 1: 1 }, anomalies: [],
      anomalies_hidden: "student-level anomaly list requires the student_level:read permission", limitations: ["Cluster structure is weak"],
      profiles: [{ kmeans_segment: 0, students: 6 }],
      results: { chosen_k: 2, silhouette_by_k: { 2: 0.17 }, interpretation: "descriptive", isolation_forest: { flagged: 1, contamination: 0.02 },
        cluster_quality: { silhouette_kmeans_chosen_k_full_data: 0.17, kmeans_seed_stability_adjusted_rand: [0.4, 0.6] },
        anomaly_diagnostics: { seed_stability_jaccard_of_flagged_sets: [0.7], validation_evidence: "None" } } } });
    render(wrap(<SegmentationPage />));
    expect(await screen.findByText("Weak cluster structure — descriptive only")).toBeInTheDocument();
    expect(screen.getByText(/NOT evidence of misconduct/)).toBeInTheDocument();
    expect(screen.getByText(/requires the student_level:read permission/)).toBeInTheDocument();
    expect(screen.queryByText("Assignments CSV")).not.toBeInTheDocument();
  });
});
