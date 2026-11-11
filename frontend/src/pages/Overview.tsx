import { Card, Col, Descriptions, Row, Tag } from "antd";
import { Link } from "react-router";
import { useApi } from "../api";
import { DataBanner, KpiRow, PageHeader, Query, type DataLabel } from "../components/common";
import { ChartCard, TrendLines } from "../viz/charts";
import { fmtInt, fmtPct, fmtNum } from "../viz/palette";

type R = Record<string, number | string | null | boolean>;
type Overview = {
  data: DataLabel; enrollment: R; enrollment_trend: R[]; performance: R; retention: Record<string, R>;
  graduation: { overall_mature: R; by_level: Record<string, R> }; admissions: R; finance: R; it: R;
};

export default function OverviewPage() {
  const q = useApi<Overview>("/api/analytics/overview");
  return (
    <>
      <PageHeader title="Institutional overview" subtitle="Headline indicators across enrolment, performance, retention, graduation, admissions, finance and IT" />
      <Query q={q}>{(d) => {
        const e = d.enrollment, p = d.performance, ff = d.retention.FALL_TO_FALL, g = d.graduation.overall_mature, a = d.admissions;
        const trend = d.enrollment_trend.map((t) => ({ term: t.term_label, headcount: t.headcount, new_students: t.new_students }));
        return (
          <>
            <DataBanner data={d.data} />
            <KpiRow items={[
              { label: `Headcount · ${e.term_label}`, value: fmtInt(e.headcount), hint: e.reporting_status === "CENSUS_SNAPSHOT_ONLY" ? "census snapshot (term in progress)" : undefined,
                delta: typeof e.yoy_change_pct === "number" ? { value: e.yoy_change_pct, text: `${fmtPct(e.yoy_change_pct)} vs same term last year` } : undefined },
              { label: "New students", value: fmtInt(e.new_students), hint: `${fmtInt(e.continuing_students)} continuing` },
              { label: `Term GPA · ${p.term_label}`, value: fmtNum(p.credit_weighted_term_gpa), hint: "credit-weighted" },
              { label: "Good standing", value: fmtPct(p.good_standing_pct), hint: `${fmtPct(p.poor_standing_pct)} warning/probation/dismissed` },
              { label: `Retention · ${ff.label}`, value: fmtPct(ff.retention_rate_pct), hint: `${ff.reporting_label}; graduates excluded` },
              { label: "Graduation rate (mature cohorts)", value: fmtPct(g.graduation_rate_pct), hint: "UG 6 y · Master's 4 y · Doctorate 6 y" },
            ]} />
            <Row gutter={[12, 12]}>
              <Col xs={24} xl={16}>
                <ChartCard title="Headcount by term" note="Census headcount per term; the latest term is a census snapshot." rows={trend}
                  columns={[{ key: "term", title: "Term" }, { key: "headcount", title: "Headcount" }, { key: "new_students", title: "New students" }]}>
                  <TrendLines rows={trend} x="term" series={[{ key: "headcount", label: "Headcount" }, { key: "new_students", label: "New students" }]} />
                </ChartCard>
              </Col>
              <Col xs={24} xl={8}>
                <Card size="small" title="Admissions funnel (all entry terms)">
                  <Descriptions size="small" column={1} items={[
                    { key: "a", label: "Applications", children: fmtInt(a.applications) },
                    { key: "o", label: "Offers", children: `${fmtInt(a.offers)} (${fmtPct(a.offer_rate_pct)} of decided)` },
                    { key: "c", label: "Acceptances", children: `${fmtInt(a.acceptances)} (yield ${fmtPct(a.yield_pct)})` },
                    { key: "p", label: "Pending decisions", children: fmtInt(a.pending) },
                  ]} />
                </Card>
                <Card size="small" title="Finance & IT" style={{ marginTop: 12 }}>
                  <Descriptions size="small" column={1} items={[
                    { key: "f", label: "Payment completion", children: fmtPct(d.finance.payment_completion_pct) },
                    { key: "h", label: "Active financial holds", children: fmtInt(d.finance.active_holds) },
                    { key: "u", label: "Mean server uptime", children: fmtPct(d.it.mean_uptime_pct, 2) },
                    { key: "l", label: "Login success rate", children: fmtPct(d.it.login_success_rate_pct) },
                  ]} />
                </Card>
              </Col>
            </Row>
            <Card size="small" title="Retention by comparison (official rates)" style={{ marginTop: 12 }}>
              <Row gutter={[12, 12]}>
                {Object.entries(d.retention).map(([k, r]) => (
                  <Col xs={24} md={8} key={k}>
                    <Descriptions size="small" column={1} title={<>{r.label} <Tag>{String(r.reporting_label)}</Tag></>} items={[
                      { key: "r", label: "Retention rate", children: fmtPct(r.retention_rate_pct) },
                      { key: "e", label: "Eligible / retained", children: `${fmtInt(r.eligible)} / ${fmtInt(r.retained)}` },
                      { key: "g", label: "Graduated before comparison (excluded)", children: fmtInt(r.graduated_before_compare) },
                    ]} />
                  </Col>
                ))}
              </Row>
              <Link to="/retention">Retention details →</Link>
            </Card>
          </>
        );
      }}</Query>
    </>
  );
}
