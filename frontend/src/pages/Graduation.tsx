import { Button, Card, Segmented, Space, Table, Tag } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useState } from "react";
import { download, qs, useApi } from "../api";
import { DataBanner, FilterBar, KpiRow, Limitations, PageHeader, Query, type DataLabel, type FilterState } from "../components/common";
import { ModelPanel } from "../components/models";
import { Bars, ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtNum, fmtPct, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Grad = {
  data: DataLabel; definitions: Record<string, string>; limitations: string[];
  kpis: { overall_mature: R | null; by_level: Record<string, R>; immature_cohort_students: number };
  cohorts: R[]; by_level: R[]; by_programme: R[]; by_school: R[]; by_entry_year: R[]; time_to_completion: R[]; time_to_completion_histogram: R[];
};
const LEVELS = ["UNDERGRADUATE", "MASTERS", "DOCTORATE"];

export default function GraduationPage() {
  const [f, setF] = useState<FilterState>({});
  const [level, setLevel] = useState("UNDERGRADUATE");
  const q = useApi<Grad>(`/api/analytics/graduation${qs(f)}`);
  return (
    <>
      <PageHeader title="Graduation" subtitle="Actual graduation within the reporting window (mature cohorts only)"
        extra={<Button icon={<DownloadOutlined />} onClick={() => download(`/api/analytics/export/graduation.csv${qs(f)}`, "graduation_export.csv")}>Export CSV</Button>} />
      <FilterBar value={f} onChange={setF} fields={["school_id", "programme_id", "gender", "nationality_iso3"]} />
      <Query q={q}>{(d) => {
        const o = d.kpis.overall_mature ?? {};
        const years = d.by_entry_year.filter((r) => r.level === level).map((r) => ({ year: String(r.entry_year), rate: r.graduation_rate_pct, cohort: r.cohort_size, final: r.reporting_label }));
        const hist = d.time_to_completion_histogram.filter((r) => r.level === level).map((r) => ({ years: `${fmtNum(r.years_from, 1)}–${fmtNum(r.years_to, 1)}`, graduates: r.graduates }));
        return (
          <>
            <DataBanner data={d.data} />
            <KpiRow items={[
              { label: "Graduation rate (all mature cohorts)", value: fmtPct(o.graduation_rate_pct), hint: `${fmtInt(o.graduated_within_period)} of ${fmtInt(o.cohort_size)} within window` },
              ...LEVELS.map((lv) => ({ label: `${nice(lv)} (${d.kpis.by_level[lv]?.window_years ?? "?"} y window)`, value: fmtPct(d.kpis.by_level[lv]?.graduation_rate_pct),
                hint: `cohort ${fmtInt(d.kpis.by_level[lv]?.cohort_size)}` })),
              { label: "Not yet graduated", value: fmtInt(o.not_yet_graduated), hint: `${fmtInt(o.still_enrolled)} still enrolled · ${fmtInt(o.left)} left` },
              { label: "Immature cohorts (not rated)", value: fmtInt(d.kpis.immature_cohort_students), hint: "window not yet ended" },
            ]} />
            <Space style={{ marginBottom: 12 }}><span>Level:</span>
              <Segmented value={level} onChange={(v) => setLevel(String(v))} options={LEVELS.map((l) => ({ value: l, label: nice(l) }))} aria-label="Level" /></Space>
            <div className="grid-2">
              <ChartCard title={`Graduation rate by entry year · ${nice(level)}`} note="Only cohorts whose completion window has ended carry a final rate." rows={years}
                columns={[{ key: "year", title: "Entry year" }, { key: "cohort", title: "Cohort" }, { key: "rate", title: "Rate %", fmt: (v) => fmtPct(v) }, { key: "final", title: "Status" }]}>
                <TrendLines rows={years} x="year" fmt={(v) => fmtPct(v, 0)} series={[{ key: "rate", label: "Graduation rate %" }]} domain={[0, 100]} />
              </ChartCard>
              <ChartCard title={`Time to completion · ${nice(level)}`} note="Years from admission at the level to graduation (graduates only)." rows={hist}
                columns={[{ key: "years", title: "Years" }, { key: "graduates", title: "Graduates" }]}>
                <Bars rows={hist} cat="years" horizontal={false} series={[{ key: "graduates", label: "Graduates" }]} />
              </ChartCard>
            </div>
            <div className="grid-2">
              <Card size="small" title="By school (mature cohorts)">
                <Table size="small" rowKey={(r) => String(r.key)} dataSource={d.by_school} pagination={false} scroll={{ x: true }}
                  columns={[{ title: "School", dataIndex: "label" }, { title: "Cohort", dataIndex: "cohort_size", render: fmtInt },
                    { title: "Within window", dataIndex: "graduated_within_period", render: fmtInt }, { title: "Rate", dataIndex: "graduation_rate_pct", render: (v) => fmtPct(v) }]} />
              </Card>
              <Card size="small" title="Median time to completion">
                <Table size="small" rowKey={(r) => String(r.level)} dataSource={d.time_to_completion} pagination={false} scroll={{ x: true }}
                  columns={[{ title: "Level", dataIndex: "level", render: nice }, { title: "Graduates", dataIndex: "graduates", render: fmtInt },
                    { title: "Median (years)", dataIndex: "median_years", render: (v) => fmtNum(v) }, { title: "P25–P75", render: (_, r) => `${fmtNum(r.p25_years)}–${fmtNum(r.p75_years)}` },
                    { title: "Within window", dataIndex: "within_period_share_pct", render: (v) => fmtPct(v) }]} />
              </Card>
            </div>
            <Card size="small" title="By programme (mature cohorts)">
              <Table size="small" rowKey={(r) => String(r.key)} dataSource={d.by_programme} scroll={{ x: true }} pagination={{ pageSize: 10, size: "small" }}
                columns={[{ title: "Programme", dataIndex: "label" }, { title: "Level", dataIndex: "level", render: nice },
                  { title: "Cohort", dataIndex: "cohort_size", render: fmtInt }, { title: "Graduated within window", dataIndex: "graduated_within_period", render: fmtInt },
                  { title: "Rate", dataIndex: "graduation_rate_pct", render: (v) => fmtPct(v), sorter: (a, b) => Number(a.graduation_rate_pct) - Number(b.graduation_rate_pct) },
                  { title: "", dataIndex: "cohort_size", render: (v: number) => (v < 30 ? <Tag color="orange">small cohort</Tag> : null) }]} />
            </Card>
            <ModelPanel module="graduation" title="Graduation — model estimates (classification and survival)" />
            <Limitations items={d.limitations} definitions={d.definitions} />
          </>
        );
      }}</Query>
    </>
  );
}
