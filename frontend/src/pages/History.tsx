import { Button, Card, Table, Tag } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { download, useApi } from "../api";
import { useMe } from "../auth";
import { PageHeader, Query } from "../components/common";
import { BandTag } from "./Predictions";

type Run = { id: number; ts: string; username: string; task: string; model: string; mode: string; n_rows: number; input_name: string;
  summary: Record<string, unknown> | null; result_file: string | null };

export default function HistoryPage() {
  const q = useApi<{ runs: Run[] }>("/api/predictions", { staleTime: 0 });
  const me = useMe();
  const canDownload = !!me?.permissions.includes("reports:export");
  return (
    <>
      <PageHeader title="Prediction history" subtitle={me?.role === "ADMIN" ? "All users' prediction runs" : "Your prediction runs"} />
      <Query q={q}>{(d) => (
        <Card size="small">
          <Table<Run> size="small" rowKey="id" dataSource={d.runs} scroll={{ x: true }} pagination={{ pageSize: 20, size: "small" }}
            columns={[
              { title: "Run", dataIndex: "id" },
              { title: "When (UTC)", dataIndex: "ts", render: (v: string) => v?.replace("T", " ").slice(0, 19) },
              ...(me?.role === "ADMIN" ? [{ title: "User", dataIndex: "username" }] : []),
              { title: "Model task", dataIndex: "task", filters: Array.from(new Set(d.runs.map((r) => r.task))).map((t) => ({ text: t, value: t })), onFilter: (v, r) => r.task === v },
              { title: "Algorithm", dataIndex: "model" },
              { title: "Mode", dataIndex: "mode", render: (v: string) => <Tag>{v}</Tag> },
              { title: "Rows", dataIndex: "n_rows" },
              { title: "Input", dataIndex: "input_name" },
              { title: "Summary", dataIndex: "summary", render: (s: Run["summary"]) => s?.bands
                ? Object.entries(s.bands as Record<string, number>).map(([b, n]) => <span key={b} style={{ marginRight: 6 }}><BandTag band={b} />{n}</span>) : "" },
              ...(canDownload ? [{ title: "", key: "dl", render: (_: unknown, r: Run) => r.result_file &&
                <Button size="small" icon={<DownloadOutlined />} aria-label={`Download run ${r.id}`} onClick={() => download(`/api/predictions/${r.id}/download`, `prediction_run_${r.id}.csv`)} /> }] : []),
            ]} />
        </Card>
      )}</Query>
    </>
  );
}
