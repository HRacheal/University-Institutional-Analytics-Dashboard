import { Authenticated, CanAccess, Refine, useGetIdentity, useLogout } from "@refinedev/core";
import { ErrorComponent, ThemedLayout, ThemedSider, ThemedTitle, useNotificationProvider } from "@refinedev/antd";
import routerProvider, { CatchAllNavigate, DocumentTitleHandler } from "@refinedev/react-router";
import { App as AntApp, Button, ConfigProvider, Dropdown, Layout, Space, Switch, Tag, theme as antTheme, Typography } from "antd";
import {
  AlertOutlined, AppstoreOutlined, AuditOutlined, BarChartOutlined, BookOutlined, ClusterOutlined, DashboardOutlined,
  ExperimentOutlined, FileTextOutlined, FundOutlined, HistoryOutlined, LineChartOutlined, LogoutOutlined, ReadOutlined,
  RiseOutlined, SettingOutlined, SolutionOutlined, TeamOutlined, UserOutlined,
} from "@ant-design/icons";
import { lazy, Suspense, useMemo, useState } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";
import { accessControlProvider, authProvider } from "./auth";
import { Loading } from "./components/common";
import { initialMode, ModeContext, saveMode } from "./theme";
import type { Mode } from "./viz/palette";
import { LoginPage, ChangePasswordPage } from "./pages/Auth";

const Overview = lazy(() => import("./pages/Overview"));
const Enrollment = lazy(() => import("./pages/Enrollment"));
const Performance = lazy(() => import("./pages/Performance"));
const Retention = lazy(() => import("./pages/Retention"));
const Graduation = lazy(() => import("./pages/Graduation"));
const Admissions = lazy(() => import("./pages/Admissions"));
const Forecasting = lazy(() => import("./pages/Forecasting"));
const Segmentation = lazy(() => import("./pages/Segmentation"));
const Predictions = lazy(() => import("./pages/Predictions"));
const History = lazy(() => import("./pages/History"));
const Models = lazy(() => import("./pages/Models"));
const Reports = lazy(() => import("./pages/Reports"));
const Operations = lazy(() => import("./pages/Operations"));
const Admin = lazy(() => import("./pages/Admin"));

const resources = [
  { name: "overview", list: "/", meta: { label: "Overview", icon: <DashboardOutlined /> } },
  { name: "enrollment", list: "/enrollment", meta: { label: "Enrolment", icon: <TeamOutlined /> } },
  { name: "performance", list: "/performance", meta: { label: "Academic performance", icon: <ReadOutlined /> } },
  { name: "retention", list: "/retention", meta: { label: "Retention", icon: <RiseOutlined /> } },
  { name: "graduation", list: "/graduation", meta: { label: "Graduation", icon: <BookOutlined /> } },
  { name: "admissions", list: "/admissions", meta: { label: "Admissions", icon: <SolutionOutlined /> } },
  { name: "operations", list: "/operations", meta: { label: "Finance & IT", icon: <FundOutlined /> } },
  { name: "ai", meta: { label: "AI & forecasting", icon: <ExperimentOutlined /> } },
  { name: "forecasting", list: "/forecasting", meta: { label: "Forecasting", icon: <LineChartOutlined />, parent: "ai" } },
  { name: "predictions", list: "/predictions", meta: { label: "Predictions", icon: <AlertOutlined />, parent: "ai" } },
  { name: "segmentation", list: "/segmentation", meta: { label: "Segmentation", icon: <ClusterOutlined />, parent: "ai" } },
  { name: "models", list: "/models", meta: { label: "Model evaluation", icon: <BarChartOutlined />, parent: "ai" } },
  { name: "history", list: "/history", meta: { label: "Prediction history", icon: <HistoryOutlined />, parent: "ai" } },
  { name: "reports", list: "/reports", meta: { label: "Reports", icon: <FileTextOutlined /> } },
  { name: "admin", list: "/admin", meta: { label: "Administration", icon: <SettingOutlined /> } },
];

function Header({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  const { data: me } = useGetIdentity<{ name: string; role: string }>();
  const { mutate: logout } = useLogout();
  const { token } = antTheme.useToken();
  return (
    <Layout.Header style={{ background: token.colorBgElevated, display: "flex", justifyContent: "flex-end", alignItems: "center",
      padding: "0 16px", height: 56, borderBottom: `1px solid ${token.colorBorderSecondary}`, position: "sticky", top: 0, zIndex: 10 }}>
      <Space size={12}>
        <Switch checkedChildren="Dark" unCheckedChildren="Light" checked={mode === "dark"} aria-label="Dark mode"
          onChange={(c) => setMode(c ? "dark" : "light")} />
        <Dropdown menu={{ items: [
          { key: "pw", icon: <AuditOutlined />, label: <a href="/change-password">Change password</a> },
          { key: "out", icon: <LogoutOutlined />, label: "Sign out", onClick: () => logout() },
        ] }}>
          <Button type="text" icon={<UserOutlined />}>
            <Typography.Text>{me?.name}</Typography.Text> <Tag style={{ marginInlineStart: 6 }}>{me?.role}</Tag>
          </Button>
        </Dropdown>
      </Space>
    </Layout.Header>
  );
}

const Title = ({ collapsed }: { collapsed: boolean }) => (
  <ThemedTitle collapsed={collapsed} text="Institutional Analytics" icon={<AppstoreOutlined />} />
);

function Guard({ resource, children }: { resource: string; children: React.ReactNode }) {
  return (
    <CanAccess resource={resource} action="list" fallback={<ErrorComponent />}>
      <Suspense fallback={<Loading />}>{children}</Suspense>
    </CanAccess>
  );
}

export default function App() {
  const [mode, setModeState] = useState<Mode>(initialMode);
  const setMode = (m: Mode) => { setModeState(m); saveMode(m); };
  const ctx = useMemo(() => ({ mode, setMode }), [mode]);
  return (
    <BrowserRouter>
      <ModeContext.Provider value={ctx}>
        <ConfigProvider theme={{ algorithm: mode === "dark" ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
          token: { colorPrimary: mode === "dark" ? "#3987e5" : "#2a78d6", borderRadius: 6,
            fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif' } }}>
          <AntApp>
            <Refine routerProvider={routerProvider} authProvider={authProvider} accessControlProvider={accessControlProvider}
              notificationProvider={useNotificationProvider} resources={resources}
              options={{ syncWithLocation: false, warnWhenUnsavedChanges: false, disableTelemetry: true, title: { text: "Institutional Analytics" } }}>
              <Routes>
                <Route element={<Authenticated key="app" fallback={<CatchAllNavigate to="/login" />}>
                  <ThemedLayout Header={() => <Header mode={mode} setMode={setMode} />} Title={Title}
                    Sider={(p) => <ThemedSider {...p} Title={Title} fixed />}>
                    <div style={{ maxWidth: 1600, margin: "0 auto" }}><Outlet /></div>
                  </ThemedLayout>
                </Authenticated>}>
                  <Route index element={<Guard resource="overview"><Overview /></Guard>} />
                  <Route path="/enrollment" element={<Guard resource="enrollment"><Enrollment /></Guard>} />
                  <Route path="/performance" element={<Guard resource="performance"><Performance /></Guard>} />
                  <Route path="/retention" element={<Guard resource="retention"><Retention /></Guard>} />
                  <Route path="/graduation" element={<Guard resource="graduation"><Graduation /></Guard>} />
                  <Route path="/admissions" element={<Guard resource="admissions"><Admissions /></Guard>} />
                  <Route path="/operations" element={<Guard resource="operations"><Operations /></Guard>} />
                  <Route path="/forecasting" element={<Guard resource="forecasting"><Forecasting /></Guard>} />
                  <Route path="/predictions" element={<Guard resource="predictions"><Predictions /></Guard>} />
                  <Route path="/segmentation" element={<Guard resource="segmentation"><Segmentation /></Guard>} />
                  <Route path="/models" element={<Guard resource="models"><Models /></Guard>} />
                  <Route path="/history" element={<Guard resource="history"><History /></Guard>} />
                  <Route path="/reports" element={<Guard resource="reports"><Reports /></Guard>} />
                  <Route path="/admin" element={<Guard resource="admin"><Admin /></Guard>} />
                  <Route path="*" element={<ErrorComponent />} />
                </Route>
                <Route element={<Authenticated key="pw" fallback={<CatchAllNavigate to="/login" />}><Outlet /></Authenticated>}>
                  <Route path="/change-password" element={<ChangePasswordPage />} />
                </Route>
                <Route path="/login" element={<LoginPage />} />
              </Routes>
              <DocumentTitleHandler handler={({ resource }) => `${resource?.meta?.label ?? "Dashboard"} · Institutional Analytics`} />
            </Refine>
          </AntApp>
        </ConfigProvider>
      </ModeContext.Provider>
    </BrowserRouter>
  );
}
