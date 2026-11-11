import { Card, Select, Space, Table, Typography } from "antd";
import { useState } from "react";
import { download, qs, useApi } from "../api";
import { DataBanner, FilterBar, KpiRow, Limitations, PageHeader, Query, type DataLabel, type FilterState, type Options } from "../components/common";
import { Bars, ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtPct, nice } from "../viz/palette";
import { Button } from "antd";
import { DownloadOutlined } from "@ant-design/icons";

type R = Record<string, unknown>;
type Enr = {
  data: DataLabel; definitions: Record<string, string>; limitations: string[]; selected_term: string; kpis: R; trend: R[];
  academic_years: R[]; by_academic_year_and_season: R[]; breakdowns: Record<string, { key: string; label: string; headcount: number; share_pct?: number }[]>;
  school_trend: R[]; mode_trend: R[];
};
type Cmp = { rows: { key: string; label: string; term_a: number; term_b: number; change: number; change_pct: number | null }[]; total: R };

const FIELDS = ["academic_year", "season", "school_id", "programme_id", "level", "nationality_iso3", "gender", "delivery_mode", "study_load"];
const BREAKDOWNS: [string, string][] = [["school", "School"], ["programme", "Programme"], ["nationality", "Nationality"], ["gender", "Gender"],
  ["study_mode", "Study mode"], ["level", "Level"], ["study_load", "Study load"], ["new_vs_continuing", "New vs continuing"]];

export default function EnrollmentPage() {
  const [f, setF] = useState<FilterState>({});
  const [term, setTerm] = useState<string>();
  const [cmp, setCmp] = useState<{ a?: string; b?: string; by: string }>({ by: "school_id" });
  const opts = useApi<Options>("/api/analytics/options");
  const q = useApi<Enr>(`/api/analytics/enrollment${qs({ ...f, term_id: term })}`);
  const c = useApi<Cmp>(cmp.a && cmp.b ? `/api/analytics/enrollment/compare${qs({ ...f, term_a: cmp.a, term_b: cmp.b, by: cmp.by })}` : null);
  const terms = (opts.data?.terms ?? []).map((t) => ({ value: t.value, label: t.label }));
  return (
    <>
      <PageHeader title="Enrolment" subtitle="Census headcount trends, composition and term comparisons"
        extra={<Space wrap>
          <Select placeholder="Term (default: latest)" allowClear style={{ width: 200 }} options={terms} value={term} onChange={setTerm} aria-label="Term" />
          <Button icon={<DownloadOutlined />} onClick={() => download(`/api/analytics/export/enrollment.csv${qs(f)}`, "enrollment_export.csv")}>Export CSV</Button>
        </Space>} />
      <FilterBar value={f} onChange={setF} fields={FIELDS} />
      <Query q={q}>{(d) => {
        const k = d.kpis;
        const trend = d.trend.map((t) => ({ term: t.term_label, headcount: t.headcount, new_students: t.new_students, continuing: t.continuing_students }));
        const seasons = d.by_academic_year_and_season.map((r) => ({ year: r.academic_year, Fall: r.FALL, Spring: r.SPRING, Summer: r.SUMMER }));
        const mode = d.mode_trend.map((r) => ({ term: r.term_label, online: r.online, face_to_face: r.face_to_face }));
        return (
          <>
            <DataBanner data={d.data} />
            <KpiRow items={[
              { label: `Headcount · ${k.term_label}`, value: fmtInt(k.headcount),
                delta: typeof k.yoy_change_pct === "number" ? { value: k.yoy_change_pct as number, text: `${fmtInt(k.yoy_change)} (${fmtPct(k.yoy_change_pct)}) vs ${fmtInt(k.same_term_last_year)} a year earlier` } : undefined,
                hint: k.reporting_status === "CENSUS_SNAPSHOT_ONLY" ? "census snapshot — term in progress" : String(k.reporting_status ?? "") },
              { label: "New students", value: fmtInt(k.new_students) },
              { label: "Continuing students", value: fmtInt(k.continuing_students) },
              { label: "Online share", value: fmtPct(k.online_share_pct) },
              { label: "Part-time share", value: fmtPct(k.part_time_share_pct) },
              { label: "International share", value: fmtPct(k.international_share_pct) },
            ]} />
            <div className="grid-2">
              <ChartCard title="Headcount per semester" rows={trend}
                columns={[{ key: "term", title: "Term" }, { key: "headcount", title: "Headcount" }, { key: "new_students", title: "New" }, { key: "continuing", title: "Continuing" }]}>
                <TrendLines rows={trend} x="term" series={[{ key: "headcount", label: "Headcount" }, { key: "new_students", label: "New" }, { key: "continuing", label: "Continuing" }]} />
              </ChartCard>
              <ChartCard title="Semester comparison by academic year" note="Census headcount of each semester, side by side per academic year." rows={seasons}
                columns={[{ key: "year", title: "Academic year" }, { key: "Fall", title: "Fall" }, { key: "Spring", title: "Spring" }, { key: "Summer", title: "Summer" }]}>
                <Bars rows={seasons} cat="year" horizontal={false} series={[{ key: "Fall", label: "Fall" }, { key: "Spring", label: "Spring" }, { key: "Summer", label: "Summer" }]} />
              </ChartCard>
              <ChartCard title="Study mode per semester" rows={mode}
                columns={[{ key: "term", title: "Term" }, { key: "face_to_face", title: "Face to face" }, { key: "online", title: "Online" }]}>
                <TrendLines rows={mode} x="term" series={[{ key: "face_to_face", label: "Face to face" }, { key: "online", label: "Online" }]} />
              </ChartCard>
              <ChartCard title="Unduplicated headcount by academic year" rows={d.academic_years}
                columns={[{ key: "academic_year", title: "Academic year" }, { key: "unduplicated_headcount", title: "Unduplicated headcount" },
                  { key: "term_enrolments", title: "Term enrolments" }, { key: "complete_year", title: "Complete year", fmt: (v) => (v ? "yes" : "in progress") }]}>
                <Bars rows={d.academic_years} cat="academic_year" horizontal={false} series={[{ key: "unduplicated_headcount", label: "Unduplicated headcount" }]} />
              </ChartCard>
            </div>
            <Typography.Title level={5}>Composition · {String(k.term_label)}</Typography.Title>
            <div className="grid-2">
              {BREAKDOWNS.map(([key, label]) => {
                const rows = (d.breakdowns[key] ?? []).map((r) => ({ ...r, label: /^[A-Z_ ]+$/.test(r.label) ? nice(r.label) : r.label }));
                return (
                  <ChartCard key={key} title={`By ${label.toLowerCase()}`} rows={rows} height={Math.max(160, Math.min(rows.length, 24) * 26 + 40)}
                    columns={[{ key: "label", title: label }, { key: "headcount", title: "Headcount" }, { key: "share_pct", title: "Share", fmt: (v) => fmtPct(v) }]}>
                    <Bars rows={rows} cat="label" series={[{ key: "headcount", label: "Headcount" }]} />
                  </ChartCard>
                );
              })}
            </div>
            <Card size="small" title="Compare two terms" style={{ marginBottom: 12 }}>
              <Space wrap style={{ marginBottom: 12 }}>
                <Select placeholder="Term A" style={{ width: 160 }} options={terms} value={cmp.a} onChange={(a) => setCmp({ ...cmp, a })} aria-label="Term A" />
                <Select placeholder="Term B" style={{ width: 160 }} options={terms} value={cmp.b} onChange={(b) => setCmp({ ...cmp, b })} aria-label="Term B" />
                <Select style={{ width: 170 }} value={cmp.by} onChange={(by) => setCmp({ ...cmp, by })} aria-label="Compare by"
                  options={[["school_id", "School"], ["programme_id", "Programme"], ["level", "Level"], ["nationality_iso3", "Nationality"], ["gender", "Gender"],
                    ["delivery_mode", "Study mode"], ["study_load", "Study load"]].map(([value, label]) => ({ value, label }))} />
              </Space>
              {c.data ? (
                <Table size="small" rowKey="key" dataSource={c.data.rows} pagination={false} scroll={{ x: true }}
                  summary={() => (
                    <Table.Summary.Row>
                      <Table.Summary.Cell index={0}><b>Total</b></Table.Summary.Cell>
                      <Table.Summary.Cell index={1}>{fmtInt(c.data!.total.term_a)}</Table.Summary.Cell>
                      <Table.Summary.Cell index={2}>{fmtInt(c.data!.total.term_b)}</Table.Summary.Cell>
                      <Table.Summary.Cell index={3}>{fmtInt(c.data!.total.change)}</Table.Summary.Cell>
                      <Table.Summary.Cell index={4}>{fmtPct(c.data!.total.change_pct)}</Table.Summary.Cell>
                    </Table.Summary.Row>)}
                  columns={[{ title: "Group", dataIndex: "label" }, { title: cmp.a, dataIndex: "term_a", render: fmtInt }, { title: cmp.b, dataIndex: "term_b", render: fmtInt },
                    { title: "Change", dataIndex: "change", render: fmtInt, sorter: (x, y) => x.change - y.change },
                    { title: "Change %", dataIndex: "change_pct", render: (v) => fmtPct(v) }]} />
              ) : <Typography.Text type="secondary">{c.isLoading ? "Loading…" : "Select two terms to compare."}</Typography.Text>}
            </Card>
            <Limitations items={d.limitations} definitions={d.definitions} />
          </>
        );
      }}</Query>
    </>
  );
}
