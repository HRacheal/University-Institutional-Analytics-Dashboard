import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorState, KpiRow, StatusTag } from "../components/common";
import { ChartCard } from "../viz/charts";
import { ApiError } from "../api";
import { wrap } from "./helpers";

describe("ChartCard", () => {
  it("switches to a table view of exactly the plotted rows", async () => {
    render(wrap(<ChartCard title="Headcount" rows={[{ term: "Fall 2025", n: 1200 }, { term: "Spring 2026", n: 1100 }]}
      columns={[{ key: "term", title: "Term" }, { key: "n", title: "Headcount" }]}><div>chart</div></ChartCard>));
    expect(screen.getByText("chart")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Table"));
    await waitFor(() => expect(screen.getByText("Spring 2026")).toBeInTheDocument());
    expect(screen.getByText("1,200")).toBeInTheDocument();
  });
  it("shows an empty state without rows", () => {
    render(wrap(<ChartCard title="X" rows={[]}><div>chart</div></ChartCard>));
    expect(screen.getByText("No data for the current filters")).toBeInTheDocument();
  });
});

describe("status and states", () => {
  it("status tags carry a text label, not colour alone", () => {
    render(wrap(<StatusTag level="critical">HIGH</StatusTag>));
    expect(screen.getByText("HIGH")).toBeInTheDocument();
  });
  it("error state explains a missing permission", () => {
    render(wrap(<ErrorState error={new ApiError(403, "missing permission: admin:users")} />));
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(screen.getByText("missing permission: admin:users")).toBeInTheDocument();
  });
  it("KPI row renders values and deltas", () => {
    render(wrap(<KpiRow items={[{ label: "Headcount", value: "1,234", delta: { value: -2, text: "-2% vs last year" } }]} />));
    expect(screen.getByText("Headcount")).toBeInTheDocument();
    expect(screen.getByText(/-2% vs last year/)).toBeInTheDocument();
  });
});
