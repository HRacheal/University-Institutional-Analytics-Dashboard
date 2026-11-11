import { Button, Card, Select, Space, Table, Tag } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useState } from "react";
import { download, qs, useApi } from "../api";
import { DataBanner, FilterBar, KpiRow, Limitations, PageHeader, Query, StatusTag, type DataLabel, type FilterState, type Options } from "../components/common";
import { ModelPanel } from "../components/models";
import { Bars, ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtNum, fmtPct, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Perf = {
  data: DataLabel; definitions: Record<string, string>; limitations: string[]; kpis: R; trend: R[]; gpa_distribution: R[];
  by_school: R[]; by_programme: R[]; school_year_trend: R[]; standing_transitions: { scope: string; rows: { from: string; to: string; students: number }[] };
  attention: { years: string[]; groups: R[] };
};

export default function PerformancePage() {
  const [f, setF] = useState<FilterState>({});
  const [term, setTerm] = useState<string>();
  const opts = useApi<Options>("/api/analytics/options");
  const q = useApi<Perf>(`/api/analytics/performance${qs({ ...f, term_id: term })}`);
  return (
    <>
      <PageHeader title="Academic performance" subtitle="Historical GPA and academic standing (recorded results)"
        extra={<Space wrap>
          <Select placeholder="Term (default: latest graded)" allowClear style={{ width: 220 }} value={term} onChange={setTerm} aria-label="Term"
            options={(opts.data?.terms ?? []).filter((t) => t.reporting_status === "COMPLETED_TERM").map((t) => ({ value: t.value, label: t.label }))} />
          <Button icon={<DownloadOutlined />} onClick={() => download(`/api/analytics/export/performance.csv${qs(f)}`, "performance_export.csv")}>Export CSV</Button>
        </Space>} />
      <FilterBar value={f} onChange={setF} fields={["academic_year", "season", "school_id", "programme_id", "level", "gender", "delivery_mode"]} />
      <Query q={q}>{(d) => {
        const k = d.kpis;
        const trend = d.trend.map((t) => ({ term: t.term_label, gpa: t.credit_weighted_term_gpa, cum: t.mean_cumulative_gpa }));
        const standing = d.trend.map((t) => ({ term: t.term_label, good: t.good_standing_pct, poor: t.poor_standing_pct }));
        const schools = Array.from(new Set(d.school_year_trend.map((r) => String(r.school))));
        const byYear: Record<string, R> = {};
        d.school_year_trend.forEach((r) => { const y = String(r.academic_year); byYear[y] = { ...(byYear[y] ?? { year: y }), [String(r.school)]: r.credit_weighted_term_gpa }; });
        const schoolRows = Object.values(byYear);
        return (
          <>
            <DataBanner data={d.data} />
            <KpiRow items={[
              { label: `Term GPA · ${k.term_label}`, value: fmtNum(k.credit_weighted_term_gpa), hint: "credit-weighted" },
              { label: "Mean cumulative GPA", value: fmtNum(k.mean_cumulative_gpa) },
              { label: "Good standing", value: fmtPct(k.good_standing_pct), hint: `${fmtInt(k.standing_good)} students` },
              { label: "Warning", value: fmtInt(k.standing_warning) },
              { label: "Probation", value: fmtInt(k.standing_probation) },
              { label: "Dismissed", value: fmtInt(k.standing_dismissed) },
            ]} />
            <div className="grid-2">
              <ChartCard title="Average GPA by semester" rows={trend}
                columns={[{ key: "term", title: "Term" }, { key: "gpa", title: "Term GPA (credit-weighted)", fmt: (v) => fmtNum(v) }, { key: "cum", title: "Mean cumulative GPA", fmt: (v) => fmtNum(v) }]}>
                <TrendLines rows={trend} x="term" fmt={(v) => fmtNum(v)} series={[{ key: "gpa", label: "Term GPA" }, { key: "cum", label: "Cumulative GPA" }]} />
              </ChartCard>
              <ChartCard title="Standing by semester" note="Poor standing = warning + probation + dismissed." rows={standing}
                columns={[{ key: "term", title: "Term" }, { key: "good", title: "Good standing %", fmt: (v) => fmtPct(v) }, { key: "poor", title: "Poor standing %", fmt: (v) => fmtPct(v) }]}>
                <TrendLines rows={standing} x="term" fmt={(v) => fmtPct(v, 0)} series={[{ key: "good", label: "Good standing %" }, { key: "poor", label: "Poor standing %" }]} />
              </ChartCard>
              <ChartCard title={`GPA distribution · ${k.term_label}`} note="Students by cumulative GPA band after the selected term." rows={d.gpa_distribution}
                columns={[{ key: "band", title: "Cumulative GPA" }, { key: "students", title: "Students" }, { key: "share_pct", title: "Share", fmt: (v) => fmtPct(v) }]}>
                <Bars rows={d.gpa_distribution} cat="band" horizontal={false} series={[{ key: "students", label: "Students" }]} />
              </ChartCard>
              <ChartCard title="GPA trend by school (academic year)" rows={schoolRows}
                columns={[{ key: "year", title: "Academic year" }, ...schools.map((s) => ({ key: s, title: s, fmt: (v: unknown) => fmtNum(v) }))]}>
                <TrendLines rows={schoolRows} x="year" fmt={(v) => fmtNum(v)} series={schools.map((s) => ({ key: s, label: s }))} />
              </ChartCard>
            </div>
            <div className="grid-2">
              <Card size="small" title="Programmes and schools needing attention">
                <Table size="small" rowKey={(r) => `${r.group_by}-${r.key}`} dataSource={d.attention.groups} pagination={false} scroll={{ x: true }}
                  locale={{ emptyText: "No group met the worsening rule" }}
                  columns={[
                    { title: "Group", dataIndex: "label", render: (v, r) => <>{v} <Tag>{nice(String(r.group_by).replace("_id", ""))}</Tag></> },
                    { title: `GPA ${d.attention.years[0] ?? ""}`, dataIndex: "gpa_before", render: (v) => fmtNum(v) },
                    { title: `GPA ${d.attention.years[1] ?? ""}`, dataIndex: "gpa_after", render: (v) => fmtNum(v) },
                    { title: "Change", dataIndex: "gpa_change", render: (v: number) => <StatusTag level={v <= -0.1 ? "serious" : "warning"}>{fmtNum(v)}</StatusTag> },
                    { title: "Poor standing Δ (pp)", dataIndex: "poor_standing_change_pp", render: (v) => fmtNum(v, 1) },
                  ]} />
              </Card>
              <Card size="small" title={`Standing transitions (${d.standing_transitions.scope})`}>
                <Table size="small" rowKey={(r) => `${r.from}-${r.to}`} dataSource={d.standing_transitions.rows} pagination={{ pageSize: 8, size: "small" }}
                  columns={[{ title: "From", dataIndex: "from", render: nice }, { title: "To (next term)", dataIndex: "to", render: nice },
                    { title: "Students", dataIndex: "students", render: fmtInt, sorter: (a, b) => a.students - b.students, defaultSortOrder: "descend" }]} />
              </Card>
            </div>
            <Card size="small" title={`By programme · ${k.term_label}`}>
              <Table size="small" rowKey="key" dataSource={d.by_programme} scroll={{ x: true }} pagination={{ pageSize: 10, size: "small" }}
                columns={[{ title: "Programme", dataIndex: "label" }, { title: "Level", dataIndex: "level", render: nice },
                  { title: "Enrolments", dataIndex: "enrolments", render: fmtInt },
                  { title: "Term GPA", dataIndex: "credit_weighted_term_gpa", render: (v) => fmtNum(v), sorter: (a, b) => Number(a.credit_weighted_term_gpa) - Number(b.credit_weighted_term_gpa) },
                  { title: "Poor standing %", dataIndex: "poor_standing_pct", render: (v) => fmtPct(v), sorter: (a, b) => Number(a.poor_standing_pct) - Number(b.poor_standing_pct) }]} />
            </Card>
            <ModelPanel module="academic_risk" title="Students who may need support — model estimates" />
            <Limitations items={d.limitations} definitions={d.definitions} />
          </>
        );
      }}</Query>
    </>
  );
}
