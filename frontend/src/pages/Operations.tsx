import { Card, Table, Tabs } from "antd";
import { useApi } from "../api";
import { DataBanner, KpiRow, Limitations, PageHeader, Query, StatusTag, type DataLabel } from "../components/common";
import { Bars, ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtNum, fmtPct, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Fin = { data: DataLabel; definitions: Record<string, string>; limitations: string[]; kpis: R; by_term: R[]; completion_distribution: R[]; payment_methods: Record<string, number> };
type It = { data: DataLabel; definitions: Record<string, string>; limitations: string[]; kpis: R; servers: R[]; incidents_by_severity: Record<string, number>;
  sync_runs_by_system: R[]; recent_sync_failures: R[] };

const money = (v: unknown) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—");

function Finance() {
  const q = useApi<Fin>("/api/analytics/finance");
  return <Query q={q}>{(d) => {
    const k = d.kpis;
    const terms = d.by_term.map((r) => ({ term: r.term_label, collection: r.collection_pct }));
    return (
      <>
        <DataBanner data={d.data} />
        <KpiRow items={[
          { label: `Total charged (${k.currency})`, value: money(k.total_charged) },
          { label: "Payment completion", value: fmtPct(k.payment_completion_pct, 2) },
          { label: `Outstanding (${k.currency})`, value: money(k.outstanding_balance), hint: `${fmtInt(k.accounts_with_outstanding)} accounts` },
          { label: "Active holds", value: fmtInt(k.active_holds), hint: `${fmtInt(k.holds_blocking_registration)} block registration` },
        ]} />
        <div className="grid-2">
          <ChartCard title="Collection rate by term" rows={terms} columns={[{ key: "term", title: "Term" }, { key: "collection", title: "Collected %", fmt: (v) => fmtPct(v, 2) }]}>
            <TrendLines rows={terms} x="term" fmt={(v) => fmtPct(v, 0)} series={[{ key: "collection", label: "Collected %" }]} />
          </ChartCard>
          <ChartCard title="Accounts by payment completion" rows={d.completion_distribution} columns={[{ key: "band", title: "Completion" }, { key: "accounts", title: "Accounts" }]}>
            <Bars rows={d.completion_distribution} cat="band" horizontal={false} series={[{ key: "accounts", label: "Accounts" }]} />
          </ChartCard>
        </div>
        <Limitations items={d.limitations} definitions={d.definitions} />
      </>
    );
  }}</Query>;
}

function IT() {
  const q = useApi<It>("/api/analytics/it");
  return <Query q={q}>{(d) => {
    const k = d.kpis;
    return (
      <>
        <DataBanner data={d.data} />
        <KpiRow items={[
          { label: "Mean server uptime", value: fmtPct(k.mean_uptime_pct, 2), hint: `${fmtInt(k.servers)} servers` },
          { label: "Incidents", value: fmtInt(k.incidents) },
          { label: "Login success rate", value: fmtPct(k.login_success_rate_pct) },
          { label: "MFA enabled", value: fmtPct(k.mfa_enabled_pct), hint: `${fmtInt(k.accounts)} accounts` },
          { label: "Extract runs (sample history)", value: fmtInt(k.sample_sync_runs), hint: `${fmtInt(k.sample_sync_failures)} failed` },
        ]} />
        <div className="grid-2">
          <Card size="small" title="Servers">
            <Table size="small" rowKey={(r) => String(r.server_id)} dataSource={d.servers} pagination={false} scroll={{ x: true }}
              columns={[{ title: "Server", dataIndex: "server_id" }, { title: "Uptime", dataIndex: "uptime_pct", render: (v: number) => (
                <StatusTag level={v >= 99.5 ? "good" : v >= 99 ? "warning" : "critical"}>{fmtNum(v, 3)}%</StatusTag>) },
                { title: "Outage days", dataIndex: "outage_days", render: fmtInt }, { title: "Degraded days", dataIndex: "degraded_days", render: fmtInt }]} />
          </Card>
          <Card size="small" title="Recent extract failures (sample history)">
            <Table size="small" rowKey={(r) => String(r.run_id)} dataSource={d.recent_sync_failures} pagination={false} scroll={{ x: true }}
              columns={[{ title: "Run", dataIndex: "run_id" }, { title: "System", dataIndex: "extracted_system" }, { title: "Date", dataIndex: "run_date" },
                { title: "Reason", dataIndex: "failure_reason", render: (v) => nice(String(v)) }]} />
          </Card>
        </div>
        <Limitations items={d.limitations} definitions={d.definitions} />
      </>
    );
  }}</Query>;
}

export default function OperationsPage() {
  return (
    <>
      <PageHeader title="Finance & IT" subtitle="Fee collection, holds, system availability and access activity" />
      <Tabs items={[{ key: "f", label: "Finance", children: <Finance /> }, { key: "i", label: "IT", children: <IT /> }]} />
    </>
  );
}
