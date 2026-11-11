import { Alert, Button, Card, Col, Descriptions, Empty, Form, Input, InputNumber, Row, Select, Space, Table, Tabs, Tag, Typography, Upload } from "antd";
import { DownloadOutlined, PlayCircleOutlined, UploadOutlined } from "@ant-design/icons";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { download, post, useApi, type ApiError } from "../api";
import { useMe } from "../auth";
import { ErrorState, Loading, PageHeader, StatusTag } from "../components/common";
import { headlineMetric, type Catalogue, type TaskInfo } from "../components/models";
import { fmtNum, fmtProb, nice } from "../viz/palette";

type Col = { name: string; type: "number" | "category"; median?: number | null; values?: string[] };
type Schema = { task: string; columns: Col[]; id_columns: string[]; example: Record<string, unknown> | null; note?: string };
type Factor = { feature: string; contribution: number; value: unknown };
export type PredRow = Record<string, unknown> & { row: number; id?: string; band?: string; top_factors?: Factor[] };
export type PredRes = {
  task: string; model: string; kind: string; loaded_via?: string; label: string; decision_support: string; class1_meaning: string | null;
  thresholds: Record<string, unknown> | null; test_metrics: Record<string, number>; warnings: string[]; interpretation?: string;
  imputed_missing?: Record<string, number>; band_rule?: string | null; seconds: number; summary: Record<string, unknown>; rows: PredRow[];
  run_id: number; rows_truncated?: boolean; cohort_rule?: string;
};

const BAND_LEVEL: Record<string, "critical" | "warning" | "good"> = { HIGH: "critical", ELEVATED: "warning", LOW: "good" };

export function BandTag({ band }: { band?: string }) {
  if (!band) return null;
  if (band in BAND_LEVEL) return <StatusTag level={BAND_LEVEL[band]}>{band}</StatusTag>;
  return <Tag>{band}</Tag>;
}

export function ResultView({ res, onDownload }: { res: PredRes; onDownload?: boolean }) {
  const me = useMe();
  const canDownload = !!me && me.permissions.includes("reports:export") && me.permissions.includes("predictions:history");
  const k = res.kind;
  const probCols = k === "multiclass" ? Object.keys(res.rows[0] ?? {}).filter((c) => c.startsWith("probability_")) : [];
  const columns = [
    { title: "#", dataIndex: "row", width: 60 },
    ...(res.rows.some((r) => r.id !== undefined) ? [{ title: "ID", dataIndex: "id" }] : []),
    ...(res.rows.some((r) => r.programme_id !== undefined) ? [{ title: "Programme", dataIndex: "programme_id" }, { title: "Level", dataIndex: "level", render: (v: unknown) => nice(String(v)) }] : []),
    ...(k === "binary" ? [
      { title: `P(${res.class1_meaning ?? "class 1"})`, dataIndex: "probability_class1", render: fmtProb, sorter: (a: PredRow, b: PredRow) => Number(a.probability_class1) - Number(b.probability_class1) },
      ...(res.rows.some((r) => r.band) ? [{ title: "Band", dataIndex: "band", render: (b: string) => <BandTag band={b} />,
        filters: ["HIGH", "ELEVATED", "LOW", "LIKELY", "UNLIKELY"].map((b) => ({ text: b, value: b })), onFilter: (v: unknown, r: PredRow) => r.band === v }] : []),
      { title: "Predicted (original threshold)", dataIndex: "predicted_class_original_threshold", render: (v: unknown) => (v === 1 ? res.class1_meaning ?? "1" : v === 0 ? "not " + (res.class1_meaning ?? "1") : "—") },
      ...(res.rows.some((r) => r.predicted_class_supplementary_threshold !== undefined) ? [{ title: "Supplementary threshold", dataIndex: "predicted_class_supplementary_threshold" }] : []),
    ] : []),
    ...(k === "multiclass" ? [{ title: "Predicted", dataIndex: "predicted_label", render: (v: unknown) => <Tag>{String(v)}</Tag> },
      ...probCols.map((c) => ({ title: `P(${c.replace("probability_", "")})`, dataIndex: c, render: fmtProb }))] : []),
    ...(k === "regression" ? [{ title: "Prediction", dataIndex: "prediction", render: (v: unknown) => fmtNum(v, 3) }] : []),
    ...(k === "survival" ? [{ title: "Relative hazard", dataIndex: "relative_hazard", render: (v: unknown) => fmtNum(v, 3) },
      { title: "Level", dataIndex: "level", render: (v: unknown) => nice(String(v)) }] : []),
  ];
  const s = res.summary;
  return (
    <Card size="small" title={<Space wrap>Results <Tag color="purple">model output</Tag><Tag>run #{res.run_id}</Tag><Tag>{res.model}</Tag>
      {res.loaded_via && res.loaded_via !== "pickle" && <Tag>{res.loaded_via}</Tag>}</Space>}
      extra={onDownload !== false && canDownload && <Button icon={<DownloadOutlined />} onClick={() => download(`/api/predictions/${res.run_id}/download`, `prediction_run_${res.run_id}.csv`)}>Download CSV</Button>}>
      <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={res.label} description={res.decision_support} />
      {res.warnings.filter((w) => !w.startsWith("version warning")).map((w, i) => <Alert key={i} type="info" showIcon style={{ marginBottom: 6 }} message={w} />)}
      {res.warnings.some((w) => w.startsWith("version warning")) && (
        <Alert type="info" showIcon style={{ marginBottom: 6 }}
          message={`Library version notice: ${res.warnings.filter((w) => w.startsWith("version warning")).length} saved component(s) were created with an older library version`}
          description={<details><summary>Details</summary><ul style={{ margin: 0, paddingLeft: 18 }}>{res.warnings.filter((w) => w.startsWith("version warning")).map((w, i) => <li key={i}>{w.replace("version warning: ", "")}</li>)}</ul>
            The restoration audit loaded every model under this environment and checked its predictions; the notice is kept for transparency.</details>} />
      )}
      <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ margin: "12px 0" }} items={[
        { key: "n", label: "Rows scored", children: String(s.n) },
        ...(s.bands ? [{ key: "b", label: "Bands", children: <Space wrap>{Object.entries(s.bands as Record<string, number>).map(([b, n]) => <span key={b}><BandTag band={b} /> {n}</span>)}</Space> }] : []),
        ...(s.threshold_original !== undefined ? [{ key: "t", label: "Original threshold", children: `${fmtNum(s.threshold_original, 3)} (maximises F1 of class 1 in CV)` }] : []),
        ...(s.mean_prediction !== undefined ? [{ key: "m", label: "Mean prediction", children: `${fmtNum(s.mean_prediction, 3)} (typical test error RMSE ${fmtNum(s.typical_error_rmse_test, 3)})` }] : []),
        ...(s.predicted_labels ? [{ key: "l", label: "Predicted labels", children: Object.entries(s.predicted_labels as Record<string, number>).map(([l, n]) => `${l}: ${n}`).join(" · ") }] : []),
        { key: "c", label: "Model test performance", children: Object.entries(res.test_metrics).slice(0, 4).map(([m, v]) => `${m.replace("test_", "")} ${fmtNum(v, 3)}`).join(" · ") || "—" },
      ]} />
      {res.band_rule && <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>{res.band_rule}</Typography.Paragraph>}
      {res.interpretation && <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>{res.interpretation}</Typography.Paragraph>}
      {res.cohort_rule && <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>Cohort rule: {res.cohort_rule}</Typography.Paragraph>}
      {res.imputed_missing && Object.keys(res.imputed_missing).length > 0 && (
        <Alert type="info" showIcon style={{ marginBottom: 8 }} message={`Missing values were imputed for ${Object.keys(res.imputed_missing).length} column(s)`}
          description={Object.entries(res.imputed_missing).slice(0, 12).map(([c, n]) => `${c} (${n})`).join(", ")} />
      )}
      {res.rows_truncated && <Alert type="info" showIcon style={{ marginBottom: 8 }} message="Showing the first 500 rows. Download the CSV for all results." />}
      <Table<PredRow> size="small" rowKey="row" dataSource={res.rows} columns={columns as never} scroll={{ x: true }} pagination={{ pageSize: 15, size: "small" }}
        expandable={res.rows.some((r) => r.top_factors?.length) ? {
          rowExpandable: (r) => !!r.top_factors?.length,
          expandedRowRender: (r) => <Factors factors={r.top_factors!} target={res.class1_meaning ?? (k === "regression" ? "the prediction" : "the predicted class")} />,
        } : undefined} />
    </Card>
  );
}

function Factors({ factors, target }: { factors: Factor[]; target: string }) {
  return (
    <div>
      <Typography.Text strong>Largest contributions for this record</Typography.Text>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 6 }}>
        Model-space attribution (TreeSHAP or coefficient × scaled value; units are probability for random forests and log-odds for boosted and linear models). ▲ pushes towards {target}, ▼ away. Associations, not causes.
      </Typography.Paragraph>
      <Table size="small" pagination={false} rowKey="feature" dataSource={factors}
        columns={[{ title: "Feature", dataIndex: "feature", render: (v) => nice(String(v)) }, { title: "Value", dataIndex: "value", render: (v) => (typeof v === "number" ? fmtNum(v, 2) : String(v ?? "—")) },
          { title: "Effect", dataIndex: "contribution", render: (v: number) => <span className="tabular">{v > 0 ? "▲" : "▼"} {fmtNum(Math.abs(v), 3)}</span> }]} />
    </div>
  );
}

function SingleForm({ task, onResult }: { task: TaskInfo; onResult: (r: PredRes) => void }) {
  const s = useApi<Schema>(`/api/models/${task.task}/schema`);
  const [form] = Form.useForm();
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  useEffect(() => { if (s.data?.example) form.setFieldsValue(s.data.example); }, [s.data, form]);
  if (s.isLoading) return <Loading />;
  if (s.error) return <ErrorState error={s.error} retry={() => s.refetch()} />;
  const cols = (s.data?.columns ?? []).filter((c) => c.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <>
      <Typography.Paragraph type="secondary">{s.data?.note ?? "Enter the record's values. Blank numbers are imputed with the training median."}</Typography.Paragraph>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search placeholder={`Filter ${s.data?.columns.length ?? 0} fields`} allowClear onChange={(e) => setFilter(e.target.value)} style={{ width: 260 }} aria-label="Filter fields" />
        <Button onClick={() => s.data?.example && form.setFieldsValue(s.data.example)}>Reset to neutral example</Button>
      </Space>
      <Form form={form} layout="vertical" size="small" onFinish={async () => {
        setBusy(true); setErr(null);
        try {
          const row = Object.fromEntries(Object.entries(form.getFieldsValue(true)).filter(([, v]) => v !== undefined && v !== null && v !== ""));
          onResult(await post<PredRes>(`/api/predict/${task.task}`, { rows: [row], explain: true }));
        } catch (e) { setErr(e as ApiError); } finally { setBusy(false); }
      }}>
        <Row gutter={12} style={{ maxHeight: 420, overflowY: "auto", overflowX: "hidden" }}>
          {cols.map((c) => (
            <Col key={c.name} xs={24} sm={12} md={8} xl={6}>
              <Form.Item name={c.name} label={nice(c.name)} tooltip={c.name} preserve>
                {c.type === "number" ? <InputNumber style={{ width: "100%" }} placeholder={c.median != null ? `median ${fmtNum(c.median, 2)}` : undefined} />
                  : <Select allowClear showSearch options={(c.values ?? []).map((v) => ({ value: v, label: v }))} />}
              </Form.Item>
            </Col>
          ))}
        </Row>
        {err && <Alert type="error" showIcon style={{ margin: "8px 0" }} message={err.message}
          description={err.details ? <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(err.details, null, 1).slice(0, 1500)}</pre> : undefined} />}
        <Button type="primary" htmlType="submit" icon={<PlayCircleOutlined />} loading={busy} style={{ marginTop: 8 }}>Predict</Button>
      </Form>
    </>
  );
}

function BatchForm({ task, onResult }: { task: TaskInfo; onResult: (r: PredRes) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Upload a CSV with the model's input columns (one row per record; up to the server's row limit). An optional ID column
        (record_id, student_id, applicant_id …) is carried into the results. Unknown categories and missing columns are reported, not guessed.
      </Typography.Paragraph>
      <Space wrap>
        <Button icon={<DownloadOutlined />} onClick={() => download(`/api/models/${task.task}/template.csv`, `${task.task}_template.csv`)}>Download template</Button>
        <Upload accept=".csv,text/csv" maxCount={1} showUploadList={false} customRequest={async ({ file }) => {
          setBusy(true); setErr(null);
          const fd = new FormData();
          fd.append("file", file as Blob);
          try { onResult(await post<PredRes>(`/api/predict/${task.task}/batch`, fd)); } catch (e) { setErr(e as ApiError); } finally { setBusy(false); }
        }}>
          <Button type="primary" icon={<UploadOutlined />} loading={busy}>Upload CSV and predict</Button>
        </Upload>
      </Space>
      {err && <Alert type="error" showIcon message={err.message}
        description={err.details ? <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(err.details, null, 1).slice(0, 2000)}</pre> : undefined} />}
    </Space>
  );
}

function CohortForm({ task, onResult }: { task: TaskInfo; onResult: (r: PredRes) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  if (!task.cohort_available) return <Empty description={task.cohort_note ?? "Cohort scoring is not available for this model."} />;
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>Scores the current cohort from the registrar feature panel. {task.cohort_note}</Typography.Paragraph>
      <Button type="primary" icon={<PlayCircleOutlined />} loading={busy} onClick={async () => {
        setBusy(true); setErr(null);
        try { onResult(await post<PredRes>(`/api/predict/${task.task}/cohort`)); } catch (e) { setErr(e as ApiError); } finally { setBusy(false); }
      }}>Score current cohort</Button>
      {err && <Alert type="error" showIcon message={err.message} />}
    </Space>
  );
}

export default function PredictionsPage() {
  const [params, setParams] = useSearchParams();
  const cat = useApi<Catalogue>("/api/models");
  const me = useMe();
  const [result, setResult] = useState<PredRes | null>(null);
  const tasks = useMemo(() => (cat.data?.tasks ?? []).filter((t) => t.predictable), [cat.data]);
  const taskId = params.get("task") ?? tasks[0]?.task;
  const task = tasks.find((t) => t.task === taskId);
  useEffect(() => setResult(null), [taskId]);
  const studentLevel = !!me?.permissions.includes("student_level:read");
  return (
    <>
      <PageHeader title="Predictions" subtitle="Run saved models on a single record, a CSV file or the current cohort" />
      {cat.isLoading ? <Loading /> : cat.error ? <ErrorState error={cat.error} retry={() => cat.refetch()} /> : (
        <>
          <Card size="small" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-start" }}>
              <Select style={{ flex: "1 1 260px", maxWidth: 420, minWidth: 0 }} value={taskId} showSearch optionFilterProp="label" aria-label="Model"
                onChange={(v) => setParams({ task: v })}
                options={["academic_risk", "retention", "graduation", "admissions", "uci_benchmark"].map((m) => ({
                  label: nice(m), options: tasks.filter((t) => t.module === m).map((t) => ({ value: t.task, label: `${t.title} (${t.zone})` })) }))
                  .concat([{ label: "Other", options: tasks.filter((t) => !["academic_risk", "retention", "graduation", "admissions", "uci_benchmark"].includes(t.module)).map((t) => ({ value: t.task, label: `${t.title} (${t.zone})` })) }])
                  .filter((g) => g.options.length)} />
              {task && <div style={{ flex: "1 1 260px", minWidth: 0 }}>
                <Typography.Text>{task.prediction_meaning}</Typography.Text><br />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{task.selected_model} · {headlineMetric(task)}</Typography.Text>
              </div>}
            </div>
            {task?.warnings.map((w, i) => <Alert key={i} type="warning" showIcon style={{ marginTop: 8 }} message={w} />)}
          </Card>
          {task && (
            <Card size="small" style={{ marginBottom: 12 }}>
              <Tabs destroyOnHidden items={[
                { key: "single", label: "Single record", children: <SingleForm key={task.task} task={task} onResult={setResult} /> },
                { key: "batch", label: "CSV batch", children: <BatchForm task={task} onResult={setResult} /> },
                ...(studentLevel ? [{ key: "cohort", label: "Current cohort", children: <CohortForm task={task} onResult={setResult} /> }] : []),
              ]} />
            </Card>
          )}
          {result && <ResultView res={result} />}
        </>
      )}
    </>
  );
}
