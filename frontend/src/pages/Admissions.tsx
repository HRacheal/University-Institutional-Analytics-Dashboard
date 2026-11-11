import { Alert, Card, Table } from "antd";
import { useState } from "react";
import { qs, useApi } from "../api";
import { DataBanner, FilterBar, KpiRow, Limitations, PageHeader, Query, type DataLabel, type FilterState } from "../components/common";
import { ModelPanel } from "../components/models";
import { Bars, ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtPct, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Adm = { data: DataLabel; definitions: Record<string, string>; limitations: string[]; kpis: R; trend: R[]; by_programme: R[]; by_school: R[];
  by_academic_year: R[]; decisions: Record<string, number> };

export default function AdmissionsPage() {
  const [f, setF] = useState<FilterState>({});
  const q = useApi<Adm>(`/api/analytics/admissions${qs(f)}`);
  return (
    <>
      <PageHeader title="Admissions" subtitle="Applications, offers, acceptances and new enrolments (recorded funnel)" />
      <FilterBar value={f} onChange={setF} fields={["academic_year", "season", "school_id", "programme_id", "level", "nationality_iso3", "gender"]} />
      <Query q={q}>{(d) => {
        const k = d.kpis;
        const funnel = d.by_academic_year.map((r) => ({ year: r.academic_year, applications: r.applications, offers: r.offers, acceptances: r.acceptances }));
        const rates = d.trend.map((r) => ({ term: r.term_label, offer: r.offer_rate_pct, yield: r.yield_pct }));
        const decisions = Object.entries(d.decisions).map(([kk, v]) => ({ decision: nice(kk), applications: v }));
        return (
          <>
            <DataBanner data={d.data} />
            <KpiRow items={[
              { label: "Applications", value: fmtInt(k.applications), hint: `${fmtInt(k.pending)} pending` },
              { label: "Offers", value: fmtInt(k.offers), hint: `offer rate ${fmtPct(k.offer_rate_pct)}` },
              { label: "Acceptances", value: fmtInt(k.acceptances), hint: `yield ${fmtPct(k.yield_pct)}` },
              { label: "New enrolments", value: fmtInt(k.new_enrolments) },
              { label: "Rejected", value: fmtInt(k.rejected) },
              { label: "Withdrawn", value: fmtInt(k.withdrawn) },
            ]} />
            <div className="grid-2">
              <ChartCard title="Funnel by academic year" rows={funnel}
                columns={[{ key: "year", title: "Academic year" }, { key: "applications", title: "Applications" }, { key: "offers", title: "Offers" }, { key: "acceptances", title: "Acceptances" }]}>
                <TrendLines rows={funnel} x="year" series={[{ key: "applications", label: "Applications" }, { key: "offers", label: "Offers" }, { key: "acceptances", label: "Acceptances" }]} />
              </ChartCard>
              <ChartCard title="Offer rate and yield by entry term" rows={rates}
                columns={[{ key: "term", title: "Entry term" }, { key: "offer", title: "Offer rate %", fmt: (v) => fmtPct(v) }, { key: "yield", title: "Yield %", fmt: (v) => fmtPct(v) }]}>
                <TrendLines rows={rates} x="term" fmt={(v) => fmtPct(v, 0)} series={[{ key: "offer", label: "Offer rate %" }, { key: "yield", label: "Yield %" }]} />
              </ChartCard>
              <ChartCard title="Decisions" rows={decisions} columns={[{ key: "decision", title: "Decision" }, { key: "applications", title: "Applications" }]}>
                <Bars rows={decisions} cat="decision" series={[{ key: "applications", label: "Applications" }]} />
              </ChartCard>
              <Card size="small" title="By school">
                <Table size="small" rowKey={(r) => String(r.key)} dataSource={d.by_school} pagination={false} scroll={{ x: true }}
                  columns={[{ title: "School", dataIndex: "label" }, { title: "Applications", dataIndex: "applications", render: fmtInt },
                    { title: "Offer rate", dataIndex: "offer_rate_pct", render: (v) => fmtPct(v) }, { title: "Yield", dataIndex: "yield_pct", render: (v) => fmtPct(v) }]} />
              </Card>
            </div>
            <Card size="small" title="By programme">
              <Table size="small" rowKey={(r) => String(r.key)} dataSource={d.by_programme} scroll={{ x: true }} pagination={{ pageSize: 10, size: "small" }}
                columns={[{ title: "Programme", dataIndex: "label" }, { title: "Applications", dataIndex: "applications", render: fmtInt, sorter: (a, b) => Number(a.applications) - Number(b.applications) },
                  { title: "Offers", dataIndex: "offers", render: fmtInt }, { title: "Offer rate", dataIndex: "offer_rate_pct", render: (v) => fmtPct(v) },
                  { title: "Acceptances", dataIndex: "acceptances", render: fmtInt }, { title: "Yield", dataIndex: "yield_pct", render: (v) => fmtPct(v) }]} />
            </Card>
            <Alert type="warning" showIcon style={{ marginTop: 12 }} message="Admissions models are not screening tools"
              description="They learn past decisions and may reproduce historical patterns, including any bias. Gender and nationality are model inputs and need a fairness review. Never use a model score to decide an application." />
            <ModelPanel module="admissions" title="Offer and acceptance — model estimates" />
            <Limitations items={d.limitations} definitions={d.definitions} />
          </>
        );
      }}</Query>
    </>
  );
}
