// Shared page pieces: KPI tiles, data-source banner, limitations, loading / error states, filter bar.
import { Alert, Card, Col, Collapse, Result, Row, Select, Skeleton, Space, Statistic, Tag, Typography, Button } from "antd";
import { CheckCircleFilled, ExclamationCircleFilled, ReloadOutlined, WarningFilled } from "@ant-design/icons";
import type { ReactNode } from "react";
import { useApi, type ApiError } from "../api";
import { STATUS } from "../viz/palette";

export type DataLabel = { is_sample_data?: boolean; label?: string; sources?: Record<string, { source: string; connector: string; label: string }> };

export function PageHeader({ title, subtitle, extra }: { title: string; subtitle?: ReactNode; extra?: ReactNode }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "space-between", alignItems: "flex-end", marginBottom: 12 }}>
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>{title}</Typography.Title>
        {subtitle && <Typography.Text type="secondary">{subtitle}</Typography.Text>}
      </div>
      {extra}
    </div>
  );
}

/** Data provenance: always visible on analytic pages. */
export function DataBanner({ data, kind = "historical" }: { data?: DataLabel; kind?: "historical" | "model" }) {
  if (!data) return null;
  const sample = data.is_sample_data !== false;
  return (
    <Alert style={{ marginBottom: 12 }} type={sample ? "warning" : "info"} showIcon
      message={kind === "model" ? "Model output — estimates, not recorded facts" : sample ? "Synthetic sample data" : "Institutional data"}
      description={<span>{data.label}{data.sources && <> · Sources: {Object.entries(data.sources).map(([d, s]) => <Tag key={d} style={{ marginInlineStart: 4 }}>{d}: {s.source}</Tag>)}</>}</span>} />
  );
}

export function Limitations({ items, definitions, title = "Definitions and limitations" }: { items?: string[]; definitions?: Record<string, string>; title?: string }) {
  if (!items?.length && !definitions) return null;
  return (
    <Collapse size="small" style={{ marginTop: 12 }} items={[{
      key: "l", label: title, children: (
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          {items?.map((l, i) => <Typography.Text key={i}><WarningFilled style={{ color: STATUS.serious, marginRight: 6 }} aria-hidden />{l}</Typography.Text>)}
          {definitions && <dl style={{ margin: 0 }}>{Object.entries(definitions).map(([k, v]) => (
            <div key={k} style={{ marginBottom: 6 }}><dt style={{ fontWeight: 600 }}>{k.replace(/_/g, " ")}</dt><dd style={{ margin: 0 }}><Typography.Text type="secondary">{v}</Typography.Text></dd></div>))}</dl>}
        </Space>),
    }]} />
  );
}

export type Kpi = { label: string; value: ReactNode; suffix?: string; hint?: ReactNode; delta?: { value: number; goodWhenUp?: boolean; text: string } };

export function KpiRow({ items }: { items: Kpi[] }) {
  return (
    <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
      {items.map((k) => (
        <Col key={k.label} xs={12} sm={12} md={8} lg={6} xl={Math.max(4, Math.floor(24 / Math.min(items.length, 6)))}>
          <Card size="small" style={{ height: "100%" }}>
            <Statistic title={k.label} value={k.value as string | number} suffix={k.suffix} valueStyle={{ fontSize: 24 }} />
            {k.delta && <DeltaText {...k.delta} />}
            {k.hint && <Typography.Text type="secondary" style={{ fontSize: 12, display: "block" }}>{k.hint}</Typography.Text>}
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function DeltaText({ value, goodWhenUp = true, text }: { value: number; goodWhenUp?: boolean; text: string }) {
  const good = value === 0 ? null : (value > 0) === goodWhenUp;
  return (
    <Typography.Text style={{ fontSize: 12 }} type={good === null ? "secondary" : good ? "success" : "danger"}>
      {value > 0 ? "▲" : value < 0 ? "▼" : "■"} {text}
    </Typography.Text>
  );
}

export function StatusTag({ level, children }: { level: "good" | "warning" | "serious" | "critical"; children: ReactNode }) {
  const icon = level === "good" ? <CheckCircleFilled /> : level === "critical" ? <ExclamationCircleFilled /> : <WarningFilled />;
  return <Tag icon={icon} color={STATUS[level]} style={{ color: level === "warning" ? "#0b0b0b" : "#fff" }}>{children}</Tag>;
}

export function Loading() {
  return <Card><Skeleton active paragraph={{ rows: 8 }} /></Card>;
}

export function ErrorState({ error, retry }: { error: ApiError | Error | null; retry?: () => void }) {
  const status = (error as ApiError)?.status;
  return (
    <Result status={status === 403 ? "403" : status === 404 ? "404" : "error"}
      title={status === 403 ? "No access" : status === 503 ? "Model artifact unavailable" : "Could not load this page"}
      subTitle={error?.message} extra={retry && <Button icon={<ReloadOutlined />} onClick={retry}>Try again</Button>} />
  );
}

/** Renders loading / error / content for a useApi query. */
export function Query<T>({ q, children }: { q: ReturnType<typeof useApi<T>>; children: (d: T) => ReactNode }) {
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!q.data) return <Loading />;
  return <>{children(q.data)}</>;
}

export type Options = Record<string, { value: string; label: string; reporting_status?: string }[]>;
export type FilterState = Record<string, string | undefined>;

const FILTER_LABELS: Record<string, string> = {
  academic_year: "Academic year", season: "Semester", school_id: "School", programme_id: "Programme", level: "Level",
  nationality_iso3: "Nationality", gender: "Gender", delivery_mode: "Study mode", study_load: "Study load",
};

export function FilterBar({ value, onChange, fields }: { value: FilterState; onChange: (v: FilterState) => void; fields: string[] }) {
  const opts = useApi<Options>("/api/analytics/options");
  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <Space wrap size={[8, 8]} role="group" aria-label="Filters">
        {fields.map((f) => (
          <Select key={f} allowClear showSearch optionFilterProp="label" placeholder={FILTER_LABELS[f] ?? f} aria-label={FILTER_LABELS[f] ?? f}
            style={{ minWidth: 150 }} value={value[f]} loading={opts.isLoading}
            options={(opts.data?.[f] ?? []).map((o) => ({ value: o.value, label: o.label }))}
            onChange={(v) => onChange({ ...value, [f]: v })} />
        ))}
        {Object.values(value).some(Boolean) && <Button onClick={() => onChange({})}>Clear filters</Button>}
      </Space>
    </Card>
  );
}
