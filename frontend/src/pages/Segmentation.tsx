import { Alert, Button, Card, Descriptions, Table, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { download, useApi } from "../api";
import { KpiRow, Limitations, PageHeader, Query, StatusTag } from "../components/common";
import { Bars, ChartCard } from "../viz/charts";
import { fmtInt, fmtNum, nice } from "../viz/palette";
import { useMe } from "../auth";

type R = Record<string, unknown>;
type Seg = { label: string; results: R & { cluster_quality: R; silhouette_by_k: Record<string, number>; chosen_k: number; anomaly_diagnostics: R; isolation_forest: R; interpretation: string };
  profiles: R[]; segment_sizes: Record<string, number>; anomalies_by_segment: Record<string, number>; n_students: number; anomalies: R[]; anomalies_hidden?: string;
  limitations: string[] };

const PROFILE_COLS = ["cumulative_gpa", "term_gpa", "credits_earned_per_year", "warning_terms_so_far", "probation_terms_so_far", "interruptions_so_far",
  "online_share_so_far", "part_time_share_so_far", "fin_payment_completion_pct", "fin_outstanding_ratio", "years_since_admission"];

export default function SegmentationPage() {
  const q = useApi<Seg>("/api/segmentation");
  const me = useMe();
  const canExport = !!me && me.permissions.includes("reports:export") && me.permissions.includes("student_level:read");
  return (
    <>
      <PageHeader title="Segmentation and anomalies" subtitle="Descriptive student groupings (k-means) and unusual records (isolation forest)"
        extra={canExport && <Button icon={<DownloadOutlined />} onClick={() => download("/api/segmentation/assignments.csv", "segment_assignments.csv")}>Assignments CSV</Button>} />
      <Query q={q}>{(d) => {
        const r = d.results, cq = r.cluster_quality, ad = r.anomaly_diagnostics;
        const sil = Object.entries(r.silhouette_by_k).map(([k, v]) => ({ k: `k=${k}`, silhouette: v }));
        const sizes = Object.entries(d.segment_sizes).map(([s, n]) => ({ segment: `Segment ${s}`, students: n, anomalies: d.anomalies_by_segment[s] ?? 0 }));
        return (
          <>
            <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="Weak cluster structure — descriptive only"
              description={`Silhouette ${fmtNum(cq.silhouette_kmeans_chosen_k_full_data, 3)} at k=${r.chosen_k} (rule of thumb: < 0.25 = no substantial structure). Segments are not natural types of student. Anomaly flags mark unusual records for data-quality review; they are NOT evidence of misconduct or of any problem with a student.`} />
            <KpiRow items={[
              { label: "Students segmented", value: fmtInt(d.n_students) },
              { label: "Segments (k)", value: String(r.chosen_k) },
              { label: "Silhouette", value: fmtNum(cq.silhouette_kmeans_chosen_k_full_data, 3), hint: "weak (< 0.25)" },
              { label: "Seed stability (ARI)", value: fmtNum(Math.min(...((cq.kmeans_seed_stability_adjusted_rand as number[]) ?? [NaN])), 2), hint: "minimum across seeds" },
              { label: "Anomalies flagged", value: fmtInt((r.isolation_forest as R).flagged), hint: `contamination ${fmtNum((r.isolation_forest as R).contamination, 2)}` },
            ]} />
            <div className="grid-2">
              <ChartCard title="Segment sizes" rows={sizes} columns={[{ key: "segment", title: "Segment" }, { key: "students", title: "Students" }, { key: "anomalies", title: "Flagged anomalies" }]}>
                <Bars rows={sizes} cat="segment" series={[{ key: "students", label: "Students" }, { key: "anomalies", label: "Flagged anomalies" }]} />
              </ChartCard>
              <ChartCard title="Silhouette by number of segments" note="Higher is better; all values are weak." rows={sil}
                columns={[{ key: "k", title: "k" }, { key: "silhouette", title: "Silhouette", fmt: (v) => fmtNum(v, 3) }]}>
                <Bars rows={sil} cat="k" horizontal={false} fmt={(v) => fmtNum(v, 2)} series={[{ key: "silhouette", label: "Silhouette" }]} />
              </ChartCard>
            </div>
            <Card size="small" title="Segment profiles (means)" style={{ marginBottom: 12 }}>
              <Table size="small" rowKey={(p) => String(p.kmeans_segment)} dataSource={d.profiles} pagination={false} scroll={{ x: true }}
                columns={[{ title: "Segment", dataIndex: "kmeans_segment" }, { title: "Students", dataIndex: "students", render: fmtInt },
                  ...PROFILE_COLS.map((c) => ({ title: nice(c.replace("fin_", "finance ")), dataIndex: c, render: (v: unknown) => fmtNum(v, 2) }))]} />
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>{r.interpretation}</Typography.Paragraph>
            </Card>
            <Card size="small" title="Anomaly list (data-quality review)">
              {d.anomalies_hidden ? <Alert type="info" showIcon message={d.anomalies_hidden} /> : (
                <Table size="small" rowKey={(a) => String(a.student_id)} dataSource={d.anomalies} scroll={{ x: true }} pagination={{ pageSize: 10, size: "small" }}
                  columns={[{ title: "Student (pseudonymous)", dataIndex: "student_id" }, { title: "Level", dataIndex: "level", render: (v) => nice(String(v)) },
                    { title: "Score", dataIndex: "anomaly_score", render: (v: number) => <StatusTag level="warning">{fmtNum(v, 3)}</StatusTag> },
                    ...[1, 2, 3].map((i) => ({ title: `Most unusual #${i}`, key: `f${i}`, render: (_: unknown, a: R) => `${nice(String(a[`feature_${i}`]))} = ${fmtNum(a[`value_${i}`], 2)} (z ${fmtNum(a[`z_${i}`], 1)})` }))]} />
              )}
              <Descriptions size="small" column={{ xs: 1, md: 2 }} style={{ marginTop: 12 }} items={[
                { key: "s", label: "Flag set stability (Jaccard across seeds)", children: fmtNum(Math.min(...((ad.seed_stability_jaccard_of_flagged_sets as number[]) ?? [NaN])), 2) },
                { key: "v", label: "Validation evidence", children: String(ad.validation_evidence ?? "—") },
              ]} />
            </Card>
            <Limitations items={d.limitations} />
          </>
        );
      }}</Query>
    </>
  );
}
