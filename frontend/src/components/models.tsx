// Model-estimate panel shown on each analytics page, visually separated from the official / historical figures.
import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from "antd";
import { ExperimentOutlined, WarningFilled } from "@ant-design/icons";
import { Link } from "react-router";
import { useApi } from "../api";
import { fmtNum } from "../viz/palette";
import { STATUS } from "../viz/palette";

export type TaskInfo = {
  task: string; module: string; kind: string; zone: string; title: string; prediction_meaning: string; status: string;
  selected_model: string | null; models: string[]; class1_meaning: string | null; class1_is_adverse: boolean | null;
  test_metrics: Record<string, number> | null; thresholds: Record<string, number | string> | null; label: string;
  artifact_present: boolean | null; predictable: boolean; cohort_available: boolean; cohort_note: string | null; warnings: string[];
};
export type Catalogue = { tasks: TaskInfo[]; decision_support: string; limitations: Record<string, string[]> };

export function headlineMetric(t: TaskInfo): string {
  const m = t.test_metrics ?? {};
  if (t.kind === "regression") return `test RMSE ${fmtNum(m.test_rmse, 3)} · R² ${fmtNum(m.test_r2, 3)}`;
  if (t.kind === "multiclass") return `test macro-F1 ${fmtNum(m.test_f1_macro, 3)} · ROC-AUC ${fmtNum(m.test_roc_auc_ovr_macro, 3)}`;
  if (t.kind === "binary") return `test ROC-AUC ${fmtNum(m.test_roc_auc, 3)} · PR-AUC ${fmtNum(m.test_pr_auc, 3)}`;
  if (t.kind === "survival") return "Cox proportional hazards (see evaluation for concordance)";
  return "";
}

export function ModelPanel({ module, title = "Model estimates (AI)", tasks: only }: { module: string; title?: string; tasks?: string[] }) {
  const q = useApi<Catalogue>("/api/models");
  if (q.error?.status === 403) return null;
  const tasks = (q.data?.tasks ?? []).filter((t) => t.module === module && (!only || only.includes(t.task)));
  return (
    <Card size="small" loading={q.isLoading} style={{ marginTop: 12, borderStyle: "dashed" }}
      title={<Space><ExperimentOutlined />{title}<Tag color="purple">model output</Tag></Space>}>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message="These are predictions from saved models, shown separately from the recorded figures above."
        description={q.data?.decision_support} />
      {(q.data?.limitations?.[module] ?? []).map((l, i) => (
        <Typography.Paragraph key={i} style={{ marginBottom: 4 }}><WarningFilled style={{ color: STATUS.serious, marginRight: 6 }} aria-hidden />{l}</Typography.Paragraph>
      ))}
      <div className="grid-3" style={{ marginTop: 12 }}>
        {tasks.map((t) => (
          <Card key={t.task} size="small" type="inner" title={t.title}
            extra={<Tag color={t.zone === "UCI" ? "blue" : "gold"}>{t.zone}</Tag>}>
            <Descriptions size="small" column={1} items={[
              { key: "m", label: "Predicts", children: t.prediction_meaning },
              { key: "s", label: "Selected model", children: t.selected_model ?? "—" },
              { key: "p", label: "Performance", children: headlineMetric(t) },
            ]} />
            {t.warnings.map((w, i) => <Typography.Paragraph key={i} type="warning" style={{ fontSize: 12, margin: "6px 0 0" }}>{w}</Typography.Paragraph>)}
            <Space style={{ marginTop: 8 }} wrap>
              <Link to={`/models?task=${t.task}`}><Button size="small">Evaluation</Button></Link>
              {t.predictable && <Link to={`/predictions?task=${t.task}`}><Button size="small" type="primary">Predict</Button></Link>}
            </Space>
          </Card>
        ))}
      </div>
    </Card>
  );
}
