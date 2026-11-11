import { Alert, Card, Select, Space, Table, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import { useApi } from "../api";
import { Limitations, PageHeader, Query, StatusTag } from "../components/common";
import { ChartCard, ForecastChart } from "../viz/charts";
import { fmtInt, fmtNum, fmtPct, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Fc = {
  label: string; series_families: R[]; selected_forecasts: R[]; backtest: R[]; conversion_rates: R[]; annual: R[]; annual_backtest: R[];
  next_terms: string[]; validation: R; fit_failures: R; settings: R; limitations: string[]; figures: string[];
};
type Hist = { series: string; history: { key: string; target_term: string; actual: number }[] };

export default function ForecastingPage() {
  const q = useApi<Fc>("/api/forecasts");
  const [series, setSeries] = useState("enrolment_headcount:TOTAL");
  const [key, setKey] = useState<string>();
  const h = useApi<Hist>(`/api/forecasts/history?series=${encodeURIComponent(series)}`);
  return (
    <>
      <PageHeader title="Forecasting" subtitle="Next-term planning forecasts with 80% prediction intervals (model output)" />
      <Query q={q}>{(d) => {
        const keys = Array.from(new Set(d.selected_forecasts.filter((r) => r.series === series).map((r) => String(r.key))));
        const k = key && keys.includes(key) ? key : keys.includes("ALL") ? "ALL" : keys[0];
        return <ForecastBody d={d} series={series} setSeries={(s) => { setSeries(s); setKey(undefined); }} k={k} keys={keys} setKey={setKey} hist={h.data} />;
      }}</Query>
    </>
  );
}

function ForecastBody({ d, series, setSeries, k, keys, setKey, hist }: {
  d: Fc; series: string; setSeries: (s: string) => void; k?: string; keys: string[]; setKey: (k: string) => void; hist?: Hist;
}) {
  const fam = d.series_families.find((f) => f.series === series || String(series).startsWith(String(f.series)));
  const sel = d.selected_forecasts.filter((r) => r.series === series && String(r.key) === k);
  const rows = useMemo(() => {
    const hrows = (hist?.history ?? []).filter((r) => String(r.key) === k).map((r) => ({ term: r.target_term, actual: r.actual } as R));
    const last = hrows[hrows.length - 1];
    const frows = sel.map((r) => ({ term: String(r.target_term), forecast: r.forecast, band: [r.pi80_low, r.pi80_high] } as R));
    if (last && frows.length) frows.unshift({ term: last.term, forecast: last.actual, band: [last.actual, last.actual] });
    const merged: R[] = [...hrows];
    frows.forEach((f) => { const i = merged.findIndex((m) => m.term === f.term); if (i >= 0) merged[i] = { ...merged[i], ...f }; else merged.push(f); });
    return merged;
  }, [hist, sel, k]);
  const cov = d.backtest.filter((b) => b.series === fam?.series);
  const families = Array.from(new Set(d.selected_forecasts.map((r) => String(r.series))));
  return (
    <>
      <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="Synthetic demonstration forecasts — for planning only"
        description="Intervals are empirical (from backtest errors). Several methods, notably ETS, had poor 80% interval coverage in backtesting: treat every interval as indicative, not a guarantee." />
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select style={{ width: 300 }} value={series} onChange={setSeries} aria-label="Series" showSearch
            options={families.map((f) => ({ value: f, label: nice(f.replace(":", " · ")) }))} />
          {keys.length > 1 && <Select style={{ width: 200 }} value={k} onChange={setKey} aria-label="Group" showSearch options={keys.map((x) => ({ value: x, label: x }))} />}
          {fam && <Typography.Text type="secondary">Selected method for this family: <b>{nice(String(fam.best_method))}</b> · backtest WAPE {fmtPct(100 * Number(fam.best_wape))}
            {" "}({fmtNum(fam.improvement_vs_seasonal_naive_pct_points, 1)} pp better than seasonal naive)</Typography.Text>}
        </Space>
      </Card>
      <ChartCard title={`${nice(series.replace(":", " · "))}${k && k !== "ALL" ? ` · ${k}` : ""}`} height={340}
        note="Actuals from backtest target terms; dashed line = forecast; shaded band = 80% prediction interval." rows={rows}
        columns={[{ key: "term", title: "Term" }, { key: "actual", title: "Actual", fmt: fmtInt }, { key: "forecast", title: "Forecast", fmt: (v) => fmtNum(v, 1) },
          { key: "band", title: "80% interval", fmt: (v) => (Array.isArray(v) ? `${fmtNum(v[0], 1)} – ${fmtNum(v[1], 1)}` : "—") }]}>
        <ForecastChart rows={rows} splitAt={String(sel[0] ? rows[rows.findIndex((r) => r.term === sel[0].target_term) - 1]?.term ?? "" : "")} />
      </ChartCard>
      <div className="grid-2" style={{ marginTop: 12 }}>
        <Card size="small" title="Next-term forecasts (selected method)">
          <Table size="small" rowKey={(r) => `${r.target_term}`} dataSource={sel} pagination={false} scroll={{ x: true }}
            columns={[{ title: "Term", dataIndex: "target_term" }, { title: "Method", dataIndex: "method", render: (v) => nice(String(v)) },
              { title: "Forecast", dataIndex: "forecast", render: (v) => fmtNum(v, 1) },
              { title: "80% interval", render: (_, r) => `${fmtNum(r.pi80_low, 1)} – ${fmtNum(r.pi80_high, 1)}` },
              { title: "Note", dataIndex: "target_term_note", render: (v) => (v ? String(v) : "") }]} />
        </Card>
        <Card size="small" title="Backtest by method (this family)">
          <Table size="small" rowKey={(r) => String(r.method)} dataSource={cov} pagination={false} scroll={{ x: true }}
            columns={[{ title: "Method", dataIndex: "method", render: (v, r) => <>{nice(String(v))} {r.method === fam?.best_method && <Tag color="blue">selected</Tag>}</> },
              { title: "WAPE", dataIndex: "wape", render: (v) => fmtPct(100 * Number(v)) },
              { title: "80% PI coverage", dataIndex: "pi80_coverage", render: (v: number) => (
                <StatusTag level={v >= 0.7 && v <= 0.9 ? "good" : v >= 0.6 ? "warning" : "critical"}>{fmtPct(100 * v, 0)}</StatusTag>) },
              { title: "Eligible", dataIndex: "eligible_for_selection", render: (v) => (v === false ? <Tag color="red">excluded</Tag> : "yes") }]} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>Nominal coverage is 80%; well below means intervals are too narrow.</Typography.Text>
        </Card>
      </div>
      <div className="grid-2">
        <Card size="small" title="Conversion-rate forecasts">
          <Table size="small" rowKey={(r) => `${r.rate}-${r.target_term}`} dataSource={d.conversion_rates} pagination={false} scroll={{ x: true }}
            columns={[{ title: "Rate", dataIndex: "rate", render: (v) => nice(String(v)) }, { title: "Term", dataIndex: "target_term" },
              { title: "Forecast", dataIndex: "forecast_mean_last3_same_season", render: (v) => fmtPct(100 * Number(v)) },
              { title: "Last-3 range", dataIndex: "range_last3" }]} />
        </Card>
        <Card size="small" title="Academic-year forecasts">
          <Table size="small" rowKey={(r) => String(r.series)} dataSource={d.annual} pagination={false} scroll={{ x: true }}
            columns={[{ title: "Series", dataIndex: "series", render: (v) => nice(String(v)) }, { title: "Method", dataIndex: "method", render: (v) => nice(String(v)) },
              { title: "Next year", dataIndex: "forecast_next", render: (v) => fmtNum(v, 1) }]} />
        </Card>
      </div>
      <Card size="small" title="Forecast validation">
        <Space wrap>
          <Tag>{fmtInt(d.validation.selected_forecasts)} selected forecasts</Tag>
          <StatusTag level={Number(d.validation.selected_non_finite) === 0 ? "good" : "critical"}>{fmtInt(d.validation.selected_non_finite)} non-finite</StatusTag>
          <StatusTag level={Number(d.validation.selected_negative) === 0 ? "good" : "critical"}>{fmtInt(d.validation.selected_negative)} negative</StatusTag>
          <StatusTag level={Number(d.fit_failures?.count ?? 0) === 0 ? "good" : "warning"}>{fmtInt(d.fit_failures?.count ?? 0)} fit failures recorded</StatusTag>
          <Tag>horizon {String(d.settings.horizon_terms)} terms · interval {String(d.settings.interval)}</Tag>
        </Space>
      </Card>
      <Limitations items={d.limitations} />
    </>
  );
}
