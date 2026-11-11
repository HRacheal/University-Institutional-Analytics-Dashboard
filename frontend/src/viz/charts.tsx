// Chart primitives (Recharts). Rules applied everywhere: one y-axis, thin marks (2px lines, rounded bar ends anchored at
// the baseline), a legend whenever there are >= 2 series, hover tooltips, recessive grid, colour by entity in fixed slot
// order, and a table view + CSV export on every chart (ChartCard) so no value depends on colour alone.
import { Empty, Segmented, Space, Table, Tooltip as AntTooltip, Typography, Button, Card } from "antd";
import { DownloadOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useState, type ReactNode } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from "recharts";
import { useViz } from "../theme";
import { rowsToCsv, saveText } from "../api";
import { fmtInt } from "./palette";

export type Series = { key: string; label: string };
type Row = Record<string, unknown>;

const axisProps = (c: ReturnType<typeof useViz>["chrome"]) => ({
  stroke: c.axis, tick: { fill: c.muted, fontSize: 11 }, tickLine: false,
});

function TooltipBox({ active, payload, label, fmt, chrome }: {
  active?: boolean; payload?: { name: string; value: unknown; color: string; dataKey: string }[]; label?: unknown;
  fmt: (v: unknown) => string; chrome: ReturnType<typeof useViz>["chrome"];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div role="tooltip" style={{ background: chrome.surface, border: `1px solid ${chrome.grid}`, borderRadius: 6, padding: "8px 10px",
      boxShadow: "0 2px 8px rgba(0,0,0,.12)", fontSize: 12, color: chrome.ink, minWidth: 140 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{String(label)}</div>
      {payload.filter((p) => p.value !== null && p.value !== undefined).map((p) => (
        <div key={p.dataKey} style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ display: "flex", gap: 6, alignItems: "center", color: chrome.ink2 }}>
            <span style={{ width: 10, height: 3, borderRadius: 2, background: p.color, display: "inline-block" }} />{p.name}
          </span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>{Array.isArray(p.value) ? p.value.map(fmt).join(" – ") : fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Card wrapper: title, optional note, chart/table toggle and CSV export of exactly the plotted rows. */
export function ChartCard({ title, note, rows, columns, children, filename, extra, height = 300 }: {
  title: string; note?: ReactNode; rows: Row[]; columns?: { key: string; title: string; fmt?: (v: unknown) => string }[];
  children: ReactNode; filename?: string; extra?: ReactNode; height?: number;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const cols: { key: string; title: string; fmt?: (v: unknown) => string }[] = columns ?? (rows[0] ? Object.keys(rows[0]).map((k) => ({ key: k, title: k })) : []);
  return (
    <Card size="small" title={<Space size={6}>{title}{note && <AntTooltip title={note}><InfoCircleOutlined aria-label="About this chart" /></AntTooltip>}</Space>}
      extra={<Space size={4} wrap>
        {extra}
        <Segmented size="small" value={view} onChange={(v) => setView(v as "chart" | "table")}
          options={[{ label: "Chart", value: "chart" }, { label: "Table", value: "table" }]} aria-label="Chart or table view" />
        <Button size="small" icon={<DownloadOutlined />} aria-label={`Download ${title} as CSV`} disabled={!rows.length}
          onClick={() => saveText(rowsToCsv(rows.map((r) => Object.fromEntries(cols.map((c) => [c.title, r[c.key]]))), title), `${filename ?? title.replace(/\W+/g, "_")}.csv`)} />
      </Space>}
      styles={{ body: { minHeight: height } }}>
      {!rows.length ? <Empty description="No data for the current filters" /> : view === "chart" ? <div style={{ width: "100%", height }}>{children}</div> : (
        <Table size="small" pagination={rows.length > 12 ? { pageSize: 12, size: "small" } : false} scroll={{ x: true, y: height - 40 }}
          rowKey={(_, i) => String(i)} dataSource={rows}
          columns={cols.map((c) => ({ title: c.title, dataIndex: c.key, key: c.key, render: (v: unknown) => (c.fmt ? c.fmt(v) : typeof v === "number" ? v.toLocaleString() : String(v ?? "—")) }))} />
      )}
    </Card>
  );
}

export function TrendLines({ rows, x, series, fmt = fmtInt, yLabel, refLine, domain }: {
  rows: Row[]; x: string; series: Series[]; fmt?: (v: unknown) => string; yLabel?: string; refLine?: { x: string; label: string };
  domain?: [number | "auto", number | "auto"];
}) {
  const { series: pal, chrome } = useViz();
  return (
    <ResponsiveContainer>
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={chrome.grid} vertical={false} />
        <XAxis dataKey={x} {...axisProps(chrome)} minTickGap={24} />
        <YAxis {...axisProps(chrome)} tickFormatter={(v) => fmt(v)} width={56} domain={domain ?? ["auto", "auto"]}
          label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", fill: chrome.muted, fontSize: 11 } : undefined} />
        <Tooltip content={<TooltipBox fmt={fmt} chrome={chrome} />} cursor={{ stroke: chrome.axis }} />
        {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: chrome.ink2 }} />}
        {refLine && <ReferenceLine x={refLine.x} stroke={chrome.muted} strokeDasharray="3 3" label={{ value: refLine.label, fill: chrome.muted, fontSize: 11, position: "top" }} />}
        {series.slice(0, 8).map((s, i) => (
          <Line key={s.key} dataKey={s.key} name={s.label} stroke={pal[i]} strokeWidth={2} dot={rows.length <= 16 ? { r: 3 } : false}
            activeDot={{ r: 5, stroke: chrome.surface, strokeWidth: 2 }} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Bars. Horizontal by default (category labels stay readable); grouped bars for up to 3 series. */
export function Bars({ rows, cat, series, fmt = fmtInt, horizontal = true, stacked = false, colorIndex }: {
  rows: Row[]; cat: string; series: Series[]; fmt?: (v: unknown) => string; horizontal?: boolean; stacked?: boolean; colorIndex?: number[];
}) {
  const { series: pal, chrome } = useViz();
  const layout = horizontal ? "vertical" : "horizontal";
  return (
    <ResponsiveContainer>
      <BarChart data={rows} layout={layout} margin={{ top: 8, right: 16, bottom: 4, left: 4 }} barCategoryGap="25%" barGap={2}>
        <CartesianGrid stroke={chrome.grid} horizontal={!horizontal} vertical={horizontal} />
        {horizontal ? <>
          <XAxis type="number" {...axisProps(chrome)} tickFormatter={(v) => fmt(v)} />
          <YAxis type="category" dataKey={cat} {...axisProps(chrome)} width={170} interval={0} tick={{ fill: chrome.ink2, fontSize: 11 }} />
        </> : <>
          <XAxis dataKey={cat} {...axisProps(chrome)} interval={0} tick={{ fill: chrome.ink2, fontSize: 11 }} />
          <YAxis {...axisProps(chrome)} tickFormatter={(v) => fmt(v)} width={56} />
        </>}
        <Tooltip content={<TooltipBox fmt={fmt} chrome={chrome} />} cursor={{ fill: chrome.grid, opacity: 0.4 }} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: chrome.ink2 }} />}
        {series.slice(0, 8).map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={pal[colorIndex?.[i] ?? i]} stackId={stacked ? "s" : undefined}
            radius={stacked ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} stroke={chrome.surface} strokeWidth={stacked ? 1 : 0}
            maxBarSize={28} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** History + forecast with an 80 % interval band. Forecast rows carry `forecast`, `band` = [low, high]. */
export function ForecastChart({ rows, fmt = fmtInt, splitAt }: { rows: Row[]; fmt?: (v: unknown) => string; splitAt?: string }) {
  const { series: pal, chrome } = useViz();
  return (
    <ResponsiveContainer>
      <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={chrome.grid} vertical={false} />
        <XAxis dataKey="term" {...axisProps(chrome)} minTickGap={20} />
        <YAxis {...axisProps(chrome)} tickFormatter={(v) => fmt(v)} width={56} />
        <Tooltip content={<TooltipBox fmt={fmt} chrome={chrome} />} cursor={{ stroke: chrome.axis }} />
        <Legend wrapperStyle={{ fontSize: 12, color: chrome.ink2 }} />
        {splitAt && <ReferenceLine x={splitAt} stroke={chrome.muted} strokeDasharray="3 3" label={{ value: "forecast →", fill: chrome.muted, fontSize: 11, position: "insideTopRight" }} />}
        <Area dataKey="band" name="80% interval" fill={chrome.band} stroke="none" fillOpacity={0.8} isAnimationActive={false} connectNulls />
        <Line dataKey="actual" name="Actual" stroke={pal[0]} strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
        <Line dataKey="forecast" name="Forecast" stroke={pal[1]} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 4 }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return <Typography.Text type="secondary" style={{ fontSize: 12 }}>{children}</Typography.Text>;
}
