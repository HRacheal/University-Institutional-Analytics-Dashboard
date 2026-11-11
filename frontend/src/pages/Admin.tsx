import { Alert, App, Button, Card, Checkbox, Descriptions, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag, Typography, Upload } from "antd";
import { CloudSyncOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, post, useApi } from "../api";
import { useMe } from "../auth";
import { DataBanner, PageHeader, Query, StatusTag, type DataLabel } from "../components/common";

type User = { id: number; username: string; full_name: string; email: string; role: string; department: string | null; is_active: boolean;
  must_change_password: boolean; created_at: string; last_login: string | null; locked_until?: string | null };
type Role = { role: string; description: string; permissions: string[]; is_system: boolean };
type Roles = { roles: Role[]; permissions: Record<string, string> };
type Integration = { id: string; department: string; name: string; connector: string; status: string; is_active_source: boolean; config: Record<string, unknown>;
  entities: string[]; last_sync_at: string | null; last_sync_status: string | null; updated_at: string; updated_by: string; imported_entities: string[]; missing_entities: string[] };
type Integrations = { integrations: Integration[]; departments: Record<string, string>; data: DataLabel };
type SyncRun = { id: number; integration_id: string; started_at: string; finished_at: string; status: string; triggered_by: string; entity: string | null;
  rows_received: number | null; rows_accepted: number | null; validation: Record<string, unknown> | null; error: string | null };

const ts = (v?: string | null) => (v ? v.replace("T", " ").slice(0, 19) : "—");
const DEPTS = ["ADMISSIONS", "FINANCE", "IT", "REGISTRAR"];

function useRefresh() {
  const qc = useQueryClient();
  return (prefix: string) => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[1] ?? "").startsWith(prefix) });
}

function Users() {
  const q = useApi<User[]>("/api/admin/users", { staleTime: 0 });
  const roles = useApi<Roles>("/api/admin/roles");
  const me = useMe();
  const refresh = useRefresh();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [reset, setReset] = useState<User | null>(null);
  const [form] = Form.useForm();
  const [rform] = Form.useForm();
  const patch = async (u: User, body: Partial<User>) => {
    try { await api(`/api/admin/users/${u.id}`, { method: "PATCH", body: JSON.stringify(body) }); message.success("Saved"); refresh("/api/admin/users"); }
    catch (e) { message.error((e as Error).message); }
  };
  const roleOpts = (roles.data?.roles ?? []).map((r) => ({ value: r.role, label: r.role }));
  return (
    <Query q={q}>{(users) => (
      <Card size="small" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>New user</Button>}>
        <Table<User> size="small" rowKey="id" dataSource={users} scroll={{ x: true }} pagination={false}
          columns={[
            { title: "Username", dataIndex: "username" }, { title: "Name", dataIndex: "full_name" }, { title: "Email", dataIndex: "email" },
            { title: "Role", dataIndex: "role", render: (v, u) => <Select size="small" value={v} options={roleOpts} style={{ width: 150 }} disabled={u.username === me?.username}
              onChange={(role) => patch(u, { role })} aria-label={`Role of ${u.username}`} /> },
            { title: "Department", dataIndex: "department", render: (v, u) => <Select size="small" allowClear value={v ?? undefined} style={{ width: 130 }}
              options={DEPTS.map((d) => ({ value: d, label: d }))} onChange={(department) => patch(u, { department: department ?? null })} aria-label={`Department of ${u.username}`} /> },
            { title: "Active", dataIndex: "is_active", render: (v, u) => <Switch size="small" checked={v} disabled={u.username === me?.username} onChange={(is_active) => patch(u, { is_active })} aria-label={`Active ${u.username}`} /> },
            { title: "Last login", dataIndex: "last_login", render: ts },
            { title: "", key: "a", render: (_, u) => <Space>
              {u.must_change_password && <Tag color="orange">must change password</Tag>}
              <Button size="small" onClick={() => { setReset(u); rform.resetFields(); }}>Reset password</Button></Space> },
          ]} />
        <Modal title="New user" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden>
          <Form form={form} layout="vertical" onFinish={async (v) => {
            try { await post("/api/admin/users", v); message.success("User created — they must change the password at first sign-in"); setOpen(false); form.resetFields(); refresh("/api/admin/users"); }
            catch (e) { message.error((e as Error).message); }
          }}>
            <Form.Item name="username" label="Username" rules={[{ required: true }, { pattern: /^[A-Za-z0-9._-]{3,80}$/, message: "3–80 letters, digits, . _ -" }]}><Input /></Form.Item>
            <Form.Item name="full_name" label="Full name"><Input /></Form.Item>
            <Form.Item name="email" label="Email"><Input type="email" /></Form.Item>
            <Form.Item name="role" label="Role" rules={[{ required: true }]}><Select options={roleOpts} /></Form.Item>
            <Form.Item name="department" label="Department"><Select allowClear options={DEPTS.map((d) => ({ value: d, label: d }))} /></Form.Item>
            <Form.Item name="password" label="Temporary password" rules={[{ required: true }, { min: 10 }]} extra="≥ 10 characters with upper, lower case and a digit; not containing the username."><Input.Password autoComplete="new-password" /></Form.Item>
          </Form>
        </Modal>
        <Modal title={`Reset password · ${reset?.username}`} open={!!reset} onCancel={() => setReset(null)} onOk={() => rform.submit()} destroyOnHidden>
          <Form form={rform} layout="vertical" onFinish={async (v) => {
            try { await post(`/api/admin/users/${reset!.id}/reset-password`, v); message.success("Password reset; the user must change it at next sign-in"); setReset(null); refresh("/api/admin/users"); }
            catch (e) { message.error((e as Error).message); }
          }}>
            <Form.Item name="new_password" label="Temporary password" rules={[{ required: true }, { min: 10 }]}><Input.Password autoComplete="new-password" /></Form.Item>
          </Form>
        </Modal>
      </Card>
    )}</Query>
  );
}

function RolesTab() {
  const q = useApi<Roles>("/api/admin/roles", { staleTime: 0 });
  const refresh = useRefresh();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  return (
    <Query q={q}>{(d) => (
      <Card size="small" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>New role</Button>}>
        <Table<Role> size="small" rowKey="role" dataSource={d.roles} pagination={false} scroll={{ x: true }}
          columns={[{ title: "Role", dataIndex: "role", render: (v, r) => <>{v} {r.is_system && <Tag>system</Tag>}</> }, { title: "Description", dataIndex: "description" },
            { title: "Permissions", dataIndex: "permissions", render: (p: string[]) => <Space wrap size={4}>{p.map((x) => <Tag key={x}>{x}</Tag>)}</Space> },
            { title: "", key: "x", render: (_, r) => !r.is_system && <Popconfirm title={`Delete role ${r.role}?`} onConfirm={async () => {
              try { await api(`/api/admin/roles/${r.role}`, { method: "DELETE" }); message.success("Deleted"); refresh("/api/admin/roles"); } catch (e) { message.error((e as Error).message); }
            }}><Button size="small" danger>Delete</Button></Popconfirm> }]} />
        <Modal title="New role" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden width={640}>
          <Form form={form} layout="vertical" onFinish={async (v) => {
            try { await post("/api/admin/roles", v); message.success("Role created"); setOpen(false); form.resetFields(); refresh("/api/admin/roles"); }
            catch (e) { message.error((e as Error).message); }
          }}>
            <Form.Item name="role" label="Role name" rules={[{ required: true }, { pattern: /^[A-Z][A-Z0-9_]+$/, message: "UPPER_CASE letters, digits, _" }]}><Input /></Form.Item>
            <Form.Item name="description" label="Description" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="permissions" label="Permissions" rules={[{ required: true }]}>
              <Checkbox.Group style={{ display: "flex", flexDirection: "column", gap: 4 }}
                options={Object.entries(d.permissions).map(([p, desc]) => ({ value: p, label: <span><b>{p}</b> — <Typography.Text type="secondary">{desc}</Typography.Text></span> }))} />
            </Form.Item>
          </Form>
        </Modal>
      </Card>
    )}</Query>
  );
}

function IntegrationsTab() {
  const q = useApi<Integrations>("/api/admin/integrations", { staleTime: 0 });
  const me = useMe();
  const refresh = useRefresh();
  const { message } = App.useApp();
  const [cfg, setCfg] = useState<Integration | null>(null);
  const [cfgText, setCfgText] = useState("");
  const [lastImport, setLastImport] = useState<{ accepted: boolean; validation: Record<string, unknown> } | null>(null);
  const after = () => { refresh("/api/admin"); refresh("/api/analytics"); };
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); message.success(ok); after(); } catch (e) { message.error((e as Error).message); after(); } };
  return (
    <Query q={q}>{(d) => (
      <>
        <DataBanner data={d.data} />
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="Departmental connectors"
          description="Each department can use the synthetic sample, validated CSV imports, or a REST API. No live departmental API is connected: REST connectors stay AWAITING_INTEGRATION until a base URL and an environment-variable token name are configured. Secrets are never stored here — only the name of the environment variable that holds them." />
        {lastImport && <Alert closable onClose={() => setLastImport(null)} style={{ marginBottom: 12 }} type={lastImport.accepted ? "success" : "error"} showIcon
          message={lastImport.accepted ? "Import accepted" : "Import rejected — nothing was stored"}
          description={<pre style={{ whiteSpace: "pre-wrap", margin: 0, maxHeight: 240, overflow: "auto" }}>{JSON.stringify(lastImport.validation, null, 1)}</pre>} />}
        {DEPTS.map((dep) => (
          <Card key={dep} size="small" style={{ marginBottom: 12 }} title={<Space>{dep}<Typography.Text type="secondary" style={{ fontWeight: 400 }}>{d.departments[dep]}</Typography.Text></Space>}>
            <Table<Integration> size="small" rowKey="id" pagination={false} scroll={{ x: true }} dataSource={d.integrations.filter((i) => i.department === dep)}
              columns={[
                { title: "Connector", dataIndex: "name", render: (v, i) => <>{v} {i.is_active_source && <Tag color="blue">active source</Tag>}</> },
                { title: "Status", dataIndex: "status", render: (s: string) => <StatusTag level={s === "ACTIVE" || s === "READY" ? "good" : s === "ERROR" ? "critical" : "warning"}>{s}</StatusTag> },
                { title: "Entities", render: (_, i) => <Space wrap size={4}>{i.entities.map((e) => <Tag key={e} color={i.connector === "sample" || i.imported_entities?.includes(e) ? "green" : undefined}>{e}</Tag>)}</Space> },
                { title: "Last sync", render: (_, i) => i.last_sync_at ? `${ts(i.last_sync_at)} · ${i.last_sync_status}` : "—" },
                { title: "", key: "act", render: (_, i) => <Space wrap>
                  {i.connector === "csv_import" && i.entities.map((e) => (
                    <Upload key={e} accept=".csv" showUploadList={false} customRequest={async ({ file }) => {
                      const fd = new FormData(); fd.append("entity", e); fd.append("file", file as Blob);
                      try { const r = await post<{ accepted: boolean; validation: Record<string, unknown> }>(`/api/admin/integrations/${i.id}/import`, fd); setLastImport(r); after(); }
                      catch (err) { message.error((err as Error).message); after(); }
                    }}><Button size="small" icon={<UploadOutlined />}>Import {e.split("/").pop()}</Button></Upload>))}
                  {i.connector === "rest_api" && me?.permissions.includes("admin:sync") && <Button size="small" icon={<CloudSyncOutlined />} onClick={() => act(() => post(`/api/admin/integrations/${i.id}/sync`), "Sync finished")}>Sync now</Button>}
                  {i.connector !== "sample" && <Button size="small" onClick={() => { setCfg(i); setCfgText(JSON.stringify(i.config, null, 2)); }}>Configure</Button>}
                  {!i.is_active_source && <Popconfirm title={`Use ${i.name} as the ${dep} data source?`} description="Dashboards will switch to this source immediately. Missing entities fall back to nothing — import them first."
                    onConfirm={() => act(() => post(`/api/admin/integrations/${i.id}/activate`), "Active source changed")}><Button size="small">Make active</Button></Popconfirm>}
                </Space> },
              ]} />
          </Card>
        ))}
        <Drawer title={`Configure · ${cfg?.name}`} open={!!cfg} onClose={() => setCfg(null)} width={520}
          extra={<Button type="primary" onClick={async () => {
            let parsed: unknown;
            try { parsed = JSON.parse(cfgText); } catch { message.error("Not valid JSON"); return; }
            await act(() => api(`/api/admin/integrations/${cfg!.id}/config`, { method: "PUT", body: JSON.stringify(parsed) }), "Configuration saved");
            setCfg(null);
          }}>Save</Button>}>
          <Typography.Paragraph type="secondary">JSON configuration. Put the <b>name</b> of an environment variable in <code>auth_env_var</code>; never paste a token here.</Typography.Paragraph>
          <Input.TextArea value={cfgText} onChange={(e) => setCfgText(e.target.value)} autoSize={{ minRows: 12 }} style={{ fontFamily: "monospace" }} aria-label="Configuration JSON" />
        </Drawer>
      </>
    )}</Query>
  );
}

function SyncRuns() {
  const q = useApi<SyncRun[]>("/api/admin/sync-runs", { staleTime: 0 });
  return <Query q={q}>{(runs) => (
    <Card size="small">
      <Table<SyncRun> size="small" rowKey="id" dataSource={runs} scroll={{ x: true }} pagination={{ pageSize: 20, size: "small" }} locale={{ emptyText: "No imports or syncs yet" }}
        expandable={{ rowExpandable: (r) => !!(r.validation || r.error), expandedRowRender: (r) => <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{r.error ?? JSON.stringify(r.validation, null, 1)}</pre> }}
        columns={[{ title: "Run", dataIndex: "id" }, { title: "Integration", dataIndex: "integration_id" }, { title: "Entity", dataIndex: "entity" },
          { title: "Status", dataIndex: "status", render: (s: string) => <StatusTag level={s === "SUCCESS" ? "good" : s === "RUNNING" ? "warning" : "critical"}>{s}</StatusTag> },
          { title: "Received / accepted", render: (_, r) => `${r.rows_received ?? "—"} / ${r.rows_accepted ?? "—"}` },
          { title: "Started", dataIndex: "started_at", render: ts }, { title: "By", dataIndex: "triggered_by" }]} />
    </Card>)}</Query>;
}

function AuditTab() {
  const [user, setUser] = useState<string>();
  const q = useApi<Record<string, unknown>[]>(`/api/admin/audit${user ? `?username=${encodeURIComponent(user)}` : ""}`, { staleTime: 0 });
  return <Query q={q}>{(rows) => (
    <Card size="small" extra={<Input.Search placeholder="Filter by username" allowClear onSearch={(v) => setUser(v || undefined)} style={{ width: 220 }} aria-label="Filter audit by username" />}>
      <Table size="small" rowKey={(r) => String(r.id)} dataSource={rows} scroll={{ x: true }} pagination={{ pageSize: 25, size: "small" }}
        columns={[{ title: "When (UTC)", dataIndex: "ts", render: (v) => ts(String(v)) }, { title: "User", dataIndex: "username" }, { title: "Role", dataIndex: "role" },
          { title: "Action", dataIndex: "action", render: (v) => <Tag>{String(v)}</Tag> }, { title: "Target", dataIndex: "target" },
          { title: "Outcome", dataIndex: "outcome", render: (v) => <StatusTag level={v === "OK" ? "good" : "critical"}>{String(v)}</StatusTag> },
          { title: "Detail", dataIndex: "detail", render: (v) => (v ? <Typography.Text style={{ fontSize: 12 }}>{JSON.stringify(v)}</Typography.Text> : "") }, { title: "IP", dataIndex: "ip" }]} />
    </Card>)}</Query>;
}

function SettingsTab() {
  const q = useApi<{ stored: { key: string; value: unknown; updated_at: string; updated_by: string }[]; runtime: Record<string, unknown> }>("/api/admin/settings", { staleTime: 0 });
  const refresh = useRefresh();
  const { message } = App.useApp();
  return <Query q={q}>{(d) => {
    const val = (k: string) => String(d.stored.find((s) => s.key === k)?.value ?? "");
    return (
      <div className="grid-2">
        <Card size="small" title="Dashboard settings">
          <Form layout="vertical" initialValues={{ institution_name: val("institution_name"), dashboard_notice: val("dashboard_notice"), risk_review_note: val("risk_review_note") }}
            onFinish={async (v) => {
              try { for (const [k, value] of Object.entries(v)) await api(`/api/admin/settings/${k}`, { method: "PUT", body: JSON.stringify({ value: value ?? "" }) });
                message.success("Settings saved"); refresh("/api/admin/settings"); } catch (e) { message.error((e as Error).message); }
            }}>
            <Form.Item name="institution_name" label="Institution name"><Input maxLength={160} /></Form.Item>
            <Form.Item name="dashboard_notice" label="Dashboard notice"><Input.TextArea maxLength={500} autoSize /></Form.Item>
            <Form.Item name="risk_review_note" label="Risk review note (shown with predictions)"><Input.TextArea maxLength={500} autoSize /></Form.Item>
            <Button type="primary" htmlType="submit">Save</Button>
          </Form>
        </Card>
        <Card size="small" title="Runtime configuration (read-only)">
          <Descriptions size="small" column={1} items={Object.entries(d.runtime).map(([k, v]) => ({ key: k, label: k.replace(/_/g, " "), children: String(v) }))} />
        </Card>
      </div>
    );
  }}</Query>;
}

export default function AdminPage() {
  const me = useMe();
  const has = (p: string) => !!me?.permissions.includes(p);
  return (
    <>
      <PageHeader title="Administration" subtitle="Users, roles, departmental integrations, synchronisation, audit log and settings" />
      <Tabs destroyOnHidden items={[
        ...(has("admin:users") ? [{ key: "u", label: "Users", children: <Users /> }] : []),
        ...(has("admin:roles") ? [{ key: "r", label: "Roles", children: <RolesTab /> }] : []),
        ...(has("admin:integrations") ? [{ key: "i", label: "Integrations", children: <IntegrationsTab /> }] : []),
        ...(has("admin:sync") ? [{ key: "s", label: "Sync runs", children: <SyncRuns /> }] : []),
        ...(has("admin:audit") ? [{ key: "a", label: "Audit log", children: <AuditTab /> }] : []),
        ...(has("admin:settings") ? [{ key: "g", label: "Settings", children: <SettingsTab /> }] : []),
      ]} />
    </>
  );
}
