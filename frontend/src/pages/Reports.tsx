import { App, Button, Card, List, Space, Typography } from "antd";
import { DownloadOutlined, FileTextOutlined } from "@ant-design/icons";
import { useState } from "react";
import { download, useApi } from "../api";
import { useMe } from "../auth";
import { PageHeader } from "../components/common";
import type { Catalogue } from "../components/models";

type Item = { title: string; description: string; path: string; file: string; perm?: string };

const EXPORTS: Item[] = [
  { title: "Enrolment", description: "Census term enrolments with school, programme, level, nationality, gender, study mode and load.", path: "/api/analytics/export/enrollment.csv", file: "enrollment_export.csv" },
  { title: "Academic performance", description: "Term GPA, cumulative GPA and academic standing per enrolment.", path: "/api/analytics/export/performance.csv", file: "performance_export.csv" },
  { title: "Retention", description: "Retention cohort members with outcome categories for all three comparisons.", path: "/api/analytics/export/retention.csv", file: "retention_export.csv" },
  { title: "Graduation", description: "Graduation cohort members with within-window status and time to degree.", path: "/api/analytics/export/graduation.csv", file: "graduation_export.csv" },
  { title: "Segment assignments", description: "Segment and anomaly flag per pseudonymous student (requires student-level access).", path: "/api/segmentation/assignments.csv", file: "segment_assignments.csv", perm: "student_level:read" },
];

export default function ReportsPage() {
  const me = useMe();
  const { message } = App.useApp();
  const cat = useApi<Catalogue>("/api/models");
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (path: string, file: string) => {
    setBusy(path);
    try { await download(path, file); message.success(`Downloaded ${file}`); } catch (e) { message.error((e as Error).message); } finally { setBusy(null); }
  };
  return (
    <>
      <PageHeader title="Reports and exports" subtitle="Download the data behind each dashboard. Every export is labelled with its data source and audited." />
      <Card size="small" title="Data exports (CSV)" style={{ marginBottom: 12 }}>
        <List dataSource={EXPORTS.filter((e) => !e.perm || me?.permissions.includes(e.perm))} renderItem={(e) => (
          <List.Item actions={[<Button key="d" icon={<DownloadOutlined />} loading={busy === e.path} onClick={() => run(e.path, e.file)}>CSV</Button>]}>
            <List.Item.Meta avatar={<FileTextOutlined />} title={e.title} description={e.description} />
          </List.Item>)} />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>Filters chosen on a dashboard page apply to that page's own "Export CSV" button.</Typography.Text>
      </Card>
      <Card size="small" title="Model templates (CSV)" style={{ marginBottom: 12 }}>
        <Typography.Paragraph type="secondary">Input templates for batch prediction, one per predictive model.</Typography.Paragraph>
        <Space wrap>
          {(cat.data?.tasks ?? []).filter((t) => t.predictable).map((t) => (
            <Button key={t.task} size="small" loading={busy === t.task} onClick={async () => { setBusy(t.task); try { await download(`/api/models/${t.task}/template.csv`, `${t.task}_template.csv`); } catch (e) { message.error((e as Error).message); } finally { setBusy(null); } }}>{t.title}</Button>
          ))}
        </Space>
      </Card>
      <Card size="small" title="Prediction results">
        <Typography.Paragraph style={{ marginBottom: 0 }}>Every prediction run is saved with its label and model details. Download results from <a href="/history">Prediction history</a>.</Typography.Paragraph>
      </Card>
    </>
  );
}
