import { Button, Card, Descriptions, Segmented, Select, Space, Table, Tag } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useState } from "react";
import { download, qs, useApi } from "../api";
import { DataBanner, FilterBar, KpiRow, Limitations, PageHeader, Query, type DataLabel, type FilterState } from "../components/common";
import { ModelPanel } from "../components/models";
import { Bars, ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtPct, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Ret = {
  data: DataLabel; definitions: Record<string, string>; limitations: string[]; comparison: string; comparison_label: string;
  selected_base_term: string; selected: R; outcomes: Record<string, number>; trend: R[]; by: Record<string, R[]>;
};
const COMPARISONS = [{ value: "FALL_TO_FALL", label: "Fall → Fall" }, { value: "SPRING_TO_SPRING", label: "Spring → Spring" }, { value: "SUMMER_TO_SUMMER", label: "Summer → Summer" }];
const MODEL_TASKS: Record<string, string[]> = {
  FALL_TO_FALL: ["syn_retention_fall_to_fall_institutional", "syn_retention_fall_to_fall_programme"],
  SPRING_TO_SPRING: ["syn_retention_spring_to_spring_institutional", "syn_retention_spring_to_spring_programme"],
  SUMMER_TO_SUMMER: ["syn_retention_summer_to_summer_institutional", "syn_retention_summer_to_summer_programme"],
};

export default function RetentionPage() {
  const [f, setF] = useState<FilterState>({});
  const [comparison, setComparison] = useState("FALL_TO_FALL");
  const [base, setBase] = useState<string>();
  const [by, setBy] = useState("school_id");
  const q = useApi<Ret>(`/api/analytics/retention${qs({ ...f, comparison, base_term: base })}`);
  return (
    <>
      <PageHeader title="Retention" subtitle="Official-style retention rates from observed re-enrolment"
        extra={<Space wrap>
          <Segmented options={COMPARISONS} value={comparison} onChange={(v) => { setComparison(String(v)); setBase(undefined); }} aria-label="Comparison" />
          <Button icon={<DownloadOutlined />} onClick={() => download(`/api/analytics/export/retention.csv${qs(f)}`, "retention_export.csv")}>Export CSV</Button>
        </Space>} />
      <FilterBar value={f} onChange={setF} fields={["school_id", "programme_id", "level", "gender", "nationality_iso3", "delivery_mode", "study_load"]} />
      <Query q={q}>{(d) => {
        const s = d.selected;
        const trend = d.trend.map((t) => ({ cohort: String(t.label).replace(" → ", "→"), inst: t.retention_rate_pct, prog: t.programme_retention_rate_pct, final: t.reporting_label }));
        const outcomes = Object.entries(d.outcomes).map(([k, v]) => ({ outcome: nice(k), students: v }));
        const byRows: R[] = (d.by[by] ?? []).map((r) => ({ ...r, label: /^[A-Z_]+$/.test(String(r.label)) ? nice(String(r.label)) : r.label }));
        return (
          <>
            <DataBanner data={d.data} />
            <Space style={{ marginBottom: 12 }} wrap>
              <span>Base term:</span>
              <Select style={{ width: 220 }} value={d.selected_base_term} onChange={setBase} aria-label="Base term"
                options={d.trend.map((t) => ({ value: String(t.base_term_id), label: String(t.label) }))} />
              <Tag color={s.is_final ? "green" : "orange"}>{String(s.reporting_label)}</Tag>
            </Space>
            <KpiRow items={[
              { label: "Institutional retention", value: fmtPct(s.retention_rate_pct), hint: String(s.label) },
              { label: "Programme retention", value: fmtPct(s.programme_retention_rate_pct) },
              { label: "Cohort size", value: fmtInt(s.cohort_size), hint: `${fmtInt(s.graduated_before_compare)} graduated before comparison (excluded)` },
              { label: "Eligible / retained", value: `${fmtInt(s.eligible)} / ${fmtInt(s.retained)}` },
              { label: "Not retained", value: fmtInt(s.not_retained), hint: `${fmtInt(s.stopped_out)} stopped out · ${fmtInt(s.left)} left` },
              ...(comparison === "SUMMER_TO_SUMMER" ? [{ label: "Continued without summer", value: fmtInt(s.continuing_skipped_optional_summer),
                hint: `summer continuation ${fmtPct(s.summer_continuation_rate_pct)}` }] : []),
            ]} />
            <div className="grid-2">
              <ChartCard title={`${d.comparison_label} retention trend`} note="Rates exclude students who graduated before the comparison census." rows={trend}
                columns={[{ key: "cohort", title: "Cohort" }, { key: "inst", title: "Institutional %", fmt: (v) => fmtPct(v) }, { key: "prog", title: "Programme %", fmt: (v) => fmtPct(v) }, { key: "final", title: "Status" }]}>
                <TrendLines rows={trend} x="cohort" fmt={(v) => fmtPct(v, 0)} series={[{ key: "inst", label: "Institutional" }, { key: "prog", label: "Programme" }]} />
              </ChartCard>
              <ChartCard title={`Outcomes · ${s.label}`} rows={outcomes} columns={[{ key: "outcome", title: "Outcome" }, { key: "students", title: "Students" }]}>
                <Bars rows={outcomes} cat="outcome" series={[{ key: "students", label: "Students" }]} />
              </ChartCard>
            </div>
            <Card size="small" title="Retention by group" extra={<Select size="small" value={by} onChange={setBy} style={{ width: 160 }} aria-label="Group by"
              options={Object.keys(d.by).map((k) => ({ value: k, label: nice(k.replace("_id", "")) }))} />}>
              <Table size="small" rowKey={(r) => String(r.key)} dataSource={byRows} scroll={{ x: true }} pagination={{ pageSize: 10, size: "small" }}
                columns={[{ title: "Group", dataIndex: "label" }, { title: "Cohort", dataIndex: "cohort_size", render: fmtInt },
                  { title: "Eligible", dataIndex: "eligible", render: fmtInt }, { title: "Retained", dataIndex: "retained", render: fmtInt },
                  { title: "Retention %", dataIndex: "retention_rate_pct", render: (v) => fmtPct(v), sorter: (a, b) => Number(a.retention_rate_pct) - Number(b.retention_rate_pct) },
                  { title: "Programme %", dataIndex: "programme_retention_rate_pct", render: (v) => fmtPct(v) },
                  { title: "Note", dataIndex: "eligible", render: (v: number) => (v < 30 ? <Tag color="orange">small group</Tag> : null) }]} />
            </Card>
            <Card size="small" title="How graduates, transfers, deferrals and breaks are treated" style={{ marginTop: 12 }}>
              <Descriptions size="small" column={1} items={Object.entries(d.definitions).map(([k2, v]) => ({ key: k2, label: nice(k2), children: v }))} />
            </Card>
            <ModelPanel module="retention" tasks={MODEL_TASKS[comparison]} title={`${d.comparison_label} retention — model estimates`} />
            <Limitations items={d.limitations} />
          </>
        );
      }}</Query>
    </>
  );
}
