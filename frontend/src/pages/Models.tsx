import { Alert, Card, Collapse, Descriptions, Image, Select, Space, Table, Tabs, Tag, Typography } from "antd";
import { useSearchParams } from "react-router";
import { useApi } from "../api";
import { ErrorState, Loading, PageHeader, Query, StatusTag } from "../components/common";
import { headlineMetric, type Catalogue, type TaskInfo } from "../components/models";
import { Bars, ChartCard } from "../viz/charts";
import { fmtInt, fmtNum, nice } from "../viz/palette";

type R = Record<string, unknown>;
type Detail = TaskInfo & { evaluation: R | null; figures: string[]; limitations: string[]; decision_support: string };

const METRIC_COLS: Record<string, string[]> = {
  binary: ["cv_pr_auc", "cv_roc_auc", "test_roc_auc", "test_pr_auc", "test_brier", "test_tuned_precision", "test_tuned_recall", "test_tuned_f1"],
  multiclass: ["cv_f1_macro", "test_f1_macro", "test_balanced_accuracy", "test_roc_auc_ovr_macro", "test_accuracy"],
  regression: ["cv_rmse", "test_rmse", "test_mae", "test_r2"],
};

function statusLevel(s: string): "good" | "warning" | "critical" {
  return s === "TRAINED" ? "good" : s.startsWith("TRAINED") ? "warning" : "critical";
}

function Catalog({ cat, onPick }: { cat: Catalogue; onPick: (t: string) => void }) {
  const st = useApi<{ environment: R; manifest_created_utc: string; tasks: R[] }>("/api/models/status");
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message="Decision support only" description={cat.decision_support} />
      <Card size="small" title="All modelling tasks" style={{ marginBottom: 12 }}>
        <Table<TaskInfo> size="small" rowKey="task" dataSource={cat.tasks} scroll={{ x: true }} pagination={false}
          onRow={(t) => ({ onClick: () => onPick(t.task), style: { cursor: "pointer" } })}
          columns={[
            { title: "Task", dataIndex: "title", render: (v, t) => <a onClick={() => onPick(t.task)}>{v}</a> },
            { title: "Module", dataIndex: "module", render: (v) => nice(v), filters: Array.from(new Set(cat.tasks.map((t) => t.module))).map((m) => ({ text: nice(m), value: m })), onFilter: (v, t) => t.module === v },
            { title: "Data", dataIndex: "zone", render: (v) => <Tag color={v === "UCI" ? "blue" : "gold"}>{v}</Tag> },
            { title: "Status", dataIndex: "status", render: (v: string) => <StatusTag level={statusLevel(v)}>{nice(v)}</StatusTag> },
            { title: "Selected model", dataIndex: "selected_model" },
            { title: "Headline", render: (_, t) => headlineMetric(t) },
            { title: "Warnings", dataIndex: "warnings", render: (w: string[]) => (w.length ? <Tag color="orange">{w.length}</Tag> : "") },
          ]} />
      </Card>
      <Collapse size="small" items={[{ key: "s", label: "Artifact restoration status", children: st.isLoading ? <Loading /> : st.error ? <ErrorState error={st.error} /> : (
        <>
          <Typography.Paragraph type="secondary">Manifest created {st.data?.manifest_created_utc}. Each artifact is SHA-256-checked when first loaded.</Typography.Paragraph>
          <Table size="small" rowKey={(r) => String(r.task)} dataSource={st.data?.tasks} pagination={false} scroll={{ x: true }}
            columns={Object.keys(st.data?.tasks?.[0] ?? {}).slice(0, 7).map((c) => ({ title: nice(c), dataIndex: c, render: (v: unknown) => (typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "object" ? JSON.stringify(v) : String(v ?? "—")) }))} />
        </>) }]} />
    </>
  );
}

function DetailView({ task }: { task: string }) {
  const q = useApi<Detail>(`/api/models/${task}`);
  return <Query q={q}>{(d) => {
    const ev = (d.evaluation ?? {}) as R;
    const models = (ev.models as R[] | undefined) ?? [];
    const cols = (METRIC_COLS[d.kind] ?? []).filter((c) => models.some((m) => m[c] !== undefined));
    const shap = ((ev.shap_top15 as [string, number][] | undefined) ?? []).map(([f, v]) => ({ feature: nice(f), importance: v }));
    const linear = ((ev.linear_top10 as [string, number][] | undefined) ?? []).map(([f, v]) => ({ feature: f, coefficient: v }));
    const checks = (ev.leakage_checks as { check: string; passed: boolean; detail: string }[] | undefined) ?? [];
    const hr = (ev.hazard_ratios as R[] | undefined) ?? [];
    const ph = (ev.ph_possible_violations as string[] | undefined) ?? [];
    const split = (ev.split as R | undefined) ?? {};
    const oot = ev.out_of_time as R | undefined;
    return (
      <>
        <Card size="small" style={{ marginBottom: 12 }} title={<Space wrap>{d.title}<Tag color={d.zone === "UCI" ? "blue" : "gold"}>{d.zone}</Tag>
          <StatusTag level={statusLevel(d.status)}>{nice(d.status)}</StatusTag></Space>}>
          <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={d.label} description={d.decision_support} />
          {d.warnings.map((w, i) => <Alert key={i} type="warning" showIcon style={{ marginBottom: 6 }} message={w} />)}
          <Descriptions size="small" column={{ xs: 1, lg: 2 }} items={[
            { key: "p", label: "Predicts", children: d.prediction_meaning },
            { key: "t", label: "Target definition", children: String(ev.target_definition ?? "—") },
            { key: "pp", label: "Prediction point", children: String(ev.prediction_point ?? "—") },
            { key: "po", label: "Population", children: String(ev.population ?? "—") },
            { key: "n", label: "Rows / features", children: `${fmtInt(ev.n_rows)} / ${fmtInt(ev.n_features ?? (ev.covariates as unknown[] | undefined)?.length)}` },
            { key: "s", label: "Split", children: `${String(split.method ?? "—")} · train ${fmtInt(split.train_rows)} · test ${fmtInt(split.test_rows)}` },
            { key: "sel", label: "Selection rule", children: `${String(ev.selection_rule ?? "—")} → ${d.selected_model}` },
            ...(d.thresholds ? [{ key: "th", label: "Thresholds", children: Object.entries(d.thresholds).map(([k, v]) => `${nice(k)}: ${typeof v === "number" ? fmtNum(v, 3) : v}`).join(" · ") }] : []),
            ...(ev.concordance_test !== undefined ? [{ key: "c", label: "Concordance (train / test)", children: `${fmtNum(ev.concordance_train, 3)} / ${fmtNum(ev.concordance_test, 3)}` }] : []),
            ...(ev.best_vs_linear_baseline ? [{ key: "bl", label: "Best vs linear baseline", children: (() => { const b = ev.best_vs_linear_baseline as R;
              return `${b.metric}: ${fmtNum(b.best, 3)} vs ${fmtNum(b.linear_baseline, 3)} (Δ ${fmtNum(b.difference, 3)}, CV SD ${fmtNum(b.cv_sd_best, 3)})`; })() }] : []),
          ]} />
        </Card>
        <Tabs items={[
          ...(models.length ? [{ key: "cmp", label: "Model comparison", children: (
            <Card size="small">
              <Table size="small" rowKey={(m) => String(m.model)} dataSource={models} pagination={false} scroll={{ x: true }}
                columns={[{ title: "Model", dataIndex: "model", render: (v: string) => <>{nice(v)} {v === d.selected_model && <Tag color="blue">selected</Tag>}</> },
                  ...cols.map((c) => ({ title: c.replace(/_/g, " "), dataIndex: c, render: (v: unknown) => fmtNum(v, 3) }))]} />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>"tuned" metrics use the original threshold chosen in cross-validation; test data was never used for selection.</Typography.Text>
            </Card>) }] : []),
          ...(shap.length ? [{ key: "shap", label: "Feature importance", children: (
            <div className="grid-2">
              <ChartCard title={`Mean |SHAP| · ${nice(String(ev.shap_model))}`} note="Global importance on the test set; associations, not causes." rows={shap} height={420}
                columns={[{ key: "feature", title: "Feature" }, { key: "importance", title: "Mean |SHAP|", fmt: (v) => fmtNum(v, 4) }]}>
                <Bars rows={shap} cat="feature" fmt={(v) => fmtNum(v, 3)} series={[{ key: "importance", label: "Mean |SHAP|" }]} />
              </ChartCard>
              {linear.length > 0 && <Card size="small" title="Largest linear-baseline coefficients">
                <Table size="small" rowKey="feature" dataSource={linear} pagination={false}
                  columns={[{ title: "Feature", dataIndex: "feature" }, { title: "Coefficient", dataIndex: "coefficient", render: (v: number) => `${v > 0 ? "▲" : "▼"} ${fmtNum(v, 3)}` }]} />
              </Card>}
            </div>) }] : []),
          ...(hr.length ? [{ key: "hr", label: "Hazard ratios", children: (
            <Card size="small">
              {ph.length > 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="Proportional-hazards assumption questionable for:"
                description={ph.map(nice).join(", ") + ". Their hazard ratios are time-averaged and should not be read as constant effects."} />}
              <Table size="small" rowKey={(r) => String(r.covariate)} dataSource={hr} pagination={false} scroll={{ x: true }}
                columns={[{ title: "Covariate", dataIndex: "covariate", render: (v: string) => <>{nice(v)} {ph.includes(v) && <Tag color="orange">PH caveat</Tag>}</> },
                  { title: "HR per SD", dataIndex: "hazard_ratio_per_sd", render: (v) => fmtNum(v, 3) },
                  { title: "95% CI", render: (_, r) => `${fmtNum(r.ci_low, 3)} – ${fmtNum(r.ci_high, 3)}` },
                  { title: "p", dataIndex: "p_value", render: (v) => fmtNum(v, 4) }]} />
            </Card>) }] : []),
          ...((ev.subgroups as R[] | undefined)?.length ? [{ key: "sub", label: "Subgroups", children: (
            <Card size="small">
              <Typography.Paragraph type="secondary">Test-set performance by group. Small groups give unstable estimates.</Typography.Paragraph>
              <Table size="small" rowKey={(r) => `${r.column}-${r.value}`} dataSource={ev.subgroups as R[]} pagination={false} scroll={{ x: true }}
                columns={Object.keys((ev.subgroups as R[])[0]).map((c) => ({ title: nice(c), dataIndex: c, render: (v: unknown) => (typeof v === "number" ? (Number.isInteger(v) ? fmtInt(v) : fmtNum(v, 3)) : nice(String(v))) }))} />
              {oot && <Descriptions size="small" style={{ marginTop: 12 }} title={`Out-of-time check (train before ${oot.cutoff})`} column={{ xs: 1, md: 3 }}
                items={Object.entries((oot.metrics as R) ?? {}).map(([k, v]) => ({ key: k, label: nice(k), children: typeof v === "number" ? fmtNum(v, 3) : String(v) }))} />}
            </Card>) }] : []),
          ...(checks.length ? [{ key: "leak", label: "Leakage checks", children: (
            <Card size="small">
              <Table size="small" rowKey="check" dataSource={checks} pagination={false} scroll={{ x: true }}
                columns={[{ title: "Check", dataIndex: "check" }, { title: "Result", dataIndex: "passed", render: (p: boolean) => <StatusTag level={p ? "good" : "critical"}>{p ? "passed" : "FAILED"}</StatusTag> },
                  { title: "Detail", dataIndex: "detail" }]} />
              {ev.excluded_leakage_columns ? <Descriptions size="small" column={1} style={{ marginTop: 12 }} title="Excluded columns (known only after the prediction point)"
                items={Object.entries(ev.excluded_leakage_columns as R).map(([k, v]) => ({ key: k, label: k, children: String(v) }))} /> : null}
            </Card>) }] : []),
          ...(d.figures.length ? [{ key: "fig", label: "Figures", children: (
            <div className="grid-2">
              {d.figures.map((f) => (
                <Card key={f} size="small" title={nice(f.split("/").pop()!.replace(".png", ""))}>
                  <Image className="figure-img" src={`/api/figures/${f}`} alt={`${d.title}: ${f.split("/").pop()}`} />
                </Card>))}
            </div>) }] : []),
        ]} />
        <Card size="small" style={{ marginTop: 12 }} title="Limitations">
          {d.limitations.map((l, i) => <Typography.Paragraph key={i}>{l}</Typography.Paragraph>)}
        </Card>
      </>
    );
  }}</Query>;
}

export default function ModelsPage() {
  const [params, setParams] = useSearchParams();
  const cat = useApi<Catalogue>("/api/models");
  const task = params.get("task");
  return (
    <>
      <PageHeader title="Model evaluation" subtitle="Saved models, their evaluation, thresholds, leakage checks and limitations"
        extra={cat.data && <Select allowClear placeholder="Choose a model task" style={{ width: 360, maxWidth: "100%" }} value={task ?? undefined} showSearch optionFilterProp="label"
          aria-label="Model task" onChange={(v) => setParams(v ? { task: v } : {})} options={cat.data.tasks.map((t) => ({ value: t.task, label: `${t.title} (${t.zone})` }))} />} />
      <Query q={cat}>{(c) => (task ? <DetailView task={task} /> : <Catalog cat={c} onPick={(t) => setParams({ task: t })} />)}</Query>
    </>
  );
}
