import { useLogin } from "@refinedev/core";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useNavigate } from "react-router";
import { post } from "../api";
import { getMe } from "../auth";

const wrap: React.CSSProperties = { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 };

export function LoginPage() {
  const { mutate: login, isPending } = useLogin<{ username: string; password: string }>();
  const [error, setError] = useState<string | null>(null);
  return (
    <div style={wrap}>
      <Card style={{ width: 380, maxWidth: "100%" }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>Institutional Analytics</Typography.Title>
        <Typography.Paragraph type="secondary">Sign in with your dashboard account.</Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        <Form layout="vertical" requiredMark={false} onFinish={(v) => {
          setError(null);
          login(v, { onSuccess: (r) => { if (!r.success) setError(r.error?.message ?? "Login failed"); } });
        }}>
          <Form.Item name="username" label="Username" rules={[{ required: true, message: "Enter your username" }]}>
            <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, message: "Enter your password" }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={isPending}>Sign in</Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 16, marginBottom: 0 }}>
          Accounts are locked for a short period after repeated failed attempts. All sign-ins are audited.
        </Typography.Paragraph>
      </Card>
    </div>
  );
}

export function ChangePasswordPage() {
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div style={wrap}>
      <Card style={{ width: 420, maxWidth: "100%" }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>Change password</Typography.Title>
        <Typography.Paragraph type="secondary">At least 10 characters with upper- and lower-case letters and a digit, not containing your username.</Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        <Form layout="vertical" requiredMark={false} onFinish={async (v) => {
          setError(null); setBusy(true);
          try {
            await post("/api/auth/change-password", { current_password: v.current, new_password: v.next });
            await getMe(true);
            nav("/");
          } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
        }}>
          <Form.Item name="current" label="Current password" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
          <Form.Item name="next" label="New password" rules={[{ required: true }, { min: 10, message: "At least 10 characters" }]}><Input.Password autoComplete="new-password" /></Form.Item>
          <Form.Item name="confirm" label="Confirm new password" dependencies={["next"]} rules={[{ required: true }, ({ getFieldValue }) => ({
            validator: (_, val) => (val === getFieldValue("next") ? Promise.resolve() : Promise.reject(new Error("Passwords do not match"))) })]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>Update password</Button>
        </Form>
      </Card>
    </div>
  );
}
