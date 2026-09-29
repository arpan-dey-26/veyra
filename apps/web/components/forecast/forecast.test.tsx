import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  attentionRows,
  FORECAST_BADGE,
  forecastByGroup,
  forecastTimeline,
  signalCounts,
} from "@/lib/forecast";
import { demandFixture, MODEL_CARD, summaryFixture } from "@/test/forecast-fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/hospital",
}));

const GET = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: vi.fn() },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const { ForecastChart } = await import("@/components/charts/forecast-chart");
const { ForecastPanel, AdminForecast, ForecastOutlook } = await import("./forecast-panel");

const res = (status: number) => new Response(null, { status });
const ok = (data: unknown) => ({ data, response: res(200) });
const fail = (status: number, detail: string) => ({ data: undefined, error: { status, code: "x", detail }, response: res(status) });

function routes(overrides: Record<string, unknown> = {}) {
  GET.mockImplementation(async (path: string, init?: { params?: { query?: { horizon?: number } } }) => {
    if (path in overrides) return overrides[path];
    if (path === "/api/v1/forecast/demand") return ok(demandFixture(init?.params?.query?.horizon ?? 7));
    if (path === "/api/v1/forecast/summary") return ok(summaryFixture());
    if (path === "/api/v1/forecast/model") return ok(MODEL_CARD);
    return fail(404, "not found");
  });
}

beforeEach(() => {
  GET.mockReset();
});

describe("forecast data mapping", () => {
  it("joins synthetic history and forecast on one timeline", () => {
    const t = forecastTimeline(demandFixture(7));
    expect(t).toHaveLength(35);
    expect(t[27]).toMatchObject({ history: expect.any(Number), predicted: null });
    expect(t[28]).toMatchObject({ key: "2026-09-28", history: null, predicted: 5.2, lower: 2.1, upper: 8.4 });
  });

  it("maps the summary to one bar per blood group and colours signals", () => {
    const bars = forecastByGroup(summaryFixture().rows, "PRBC");
    expect(bars.map((b) => b.key)).toEqual(["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]);
    expect(bars.at(-1)).toMatchObject({ label: "O−", value: 24, tone: "critical" });
    expect(bars[0]?.detail).toContain("2.0/day forecast vs 2.0/day last 28 days");
  });

  it("puts pressure and high signals first", () => {
    const first = attentionRows(summaryFixture())[0];
    expect(first).toMatchObject({ blood_group: "O-", component: "PRBC", pressure: "pressure" });
    expect(signalCounts(summaryFixture())).toEqual({ elevated: 0, high: 1 });
  });
});

describe("ForecastChart", () => {
  it("draws history, forecast and interval with a legend and an accessible label", () => {
    render(<ForecastChart title="O+ PRBC" points={forecastTimeline(demandFixture(7))} />);
    const img = screen.getByRole("img", { name: /28 days of synthetic history and a 7-day forecast/ });
    for (const series of ["history", "forecast", "interval"]) {
      expect(img.querySelector(`[data-series="${series}"]`)).not.toBeNull();
    }
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("History (synthetic)");
    expect(screen.getByText("Today")).toBeInTheDocument();
  });

  it("offers a table with every day", () => {
    render(<ForecastChart title="O+ PRBC" points={forecastTimeline(demandFixture(14))} />);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByTestId("forecast-table");
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 28 + 14);
    expect(table).toHaveTextContent("2.1–8.4");
  });

  it("shows an empty state instead of a flat chart", () => {
    const empty = demandFixture(7, {
      history: demandFixture(7).history.map((h) => ({ ...h, demand: 0 })),
      forecast: demandFixture(7).forecast.map((p) => ({ ...p, predicted: 0, lower: 0, upper: 0 })),
    });
    render(<ForecastChart title="AB− FFP" points={forecastTimeline(empty)} />);
    expect(screen.getByText("No demand to show for this selection.")).toBeInTheDocument();
  });
});

describe("ForecastPanel", () => {
  it("renders the hospital forecast with the prototype disclaimer and model label", async () => {
    routes();
    render(<ForecastPanel kind="HOSPITAL" />);
    expect(screen.getByTestId("forecast-disclaimer")).toHaveTextContent(FORECAST_BADGE);
    expect(screen.getByTestId("forecast-disclaimer")).toHaveTextContent("not a certified medical prediction system");
    expect(await screen.findByTestId("model-label")).toHaveTextContent("veyra-demand-gbm v1.0.0 · trained on synthetic data");
    expect(screen.getByText("Prototype indicator, not a medical alert")).toBeInTheDocument();
    expect(await screen.findByText(/Upcoming demand by blood group/)).toBeInTheDocument();
    expect(screen.getByText("Demand signals")).toBeInTheDocument();
    expect(screen.queryByTestId("supply-table")).not.toBeInTheDocument();
  });

  it("refetches when the horizon changes", async () => {
    routes();
    render(<ForecastPanel kind="HOSPITAL" />);
    await screen.findByTestId("model-label");
    fireEvent.change(screen.getByLabelText("Forecast horizon"), { target: { value: "14" } });
    await waitFor(() =>
      expect(GET).toHaveBeenCalledWith("/api/v1/forecast/demand", { params: { query: { blood_group: "O+", component: "PRBC", horizon: 14 } } }),
    );
    expect(await screen.findByText("Forecast, next 14 days")).toBeInTheDocument();
  });

  it("shows blood-bank supply vs forecast with pressure bands", async () => {
    routes();
    render(<ForecastPanel kind="BLOOD_BANK" />);
    const table = await screen.findByTestId("supply-table");
    const first = within(table).getAllByRole("row")[1]!;
    expect(first).toHaveTextContent("O− · PRBC");
    expect(first).toHaveTextContent("Pressure");
    expect(table).toHaveTextContent("0.6 d");
  });

  it("shows an error state with retry", async () => {
    routes({ "/api/v1/forecast/demand": fail(500, "Model unavailable") });
    render(<ForecastPanel kind="HOSPITAL" />);
    expect(await screen.findByText("Forecast unavailable")).toBeInTheDocument();
    routes();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("model-label")).toBeInTheDocument();
  });
});

describe("ForecastOutlook", () => {
  it("summarises signals and pressure and opens the forecast tab", async () => {
    routes();
    const onOpen = vi.fn();
    render(<ForecastOutlook onOpen={onOpen} />);
    const card = await screen.findByTestId("forecast-outlook");
    expect(card).toHaveTextContent("1 high and 0 elevated demand signals. 1 stock lines under pressure.");
    expect(card).toHaveTextContent(FORECAST_BADGE);
    fireEvent.click(within(card).getByRole("button", { name: "Open forecast" }));
    expect(onOpen).toHaveBeenCalled();
  });
});

describe("AdminForecast", () => {
  it("shows the network forecast and the model evaluation", async () => {
    routes({ "/api/v1/forecast/summary": ok(summaryFixture("network")) });
    render(<AdminForecast />);
    const section = await screen.findByTestId("admin-forecast");
    expect(section).toHaveTextContent("2 hospitals · 1 high · 0 elevated");
    const evalTable = within(section).getByTestId("model-eval");
    expect(evalTable).toHaveTextContent("Seasonal baseline");
    expect(evalTable).toHaveTextContent("Gradient-boosted trees");
    expect(evalTable).toHaveTextContent("1.07");
    expect(within(section).getByTestId("forecast-disclaimer")).toHaveTextContent("not clinical guidance");
  });

  it("shows an empty state for a network without hospitals", async () => {
    routes({ "/api/v1/forecast/summary": ok(summaryFixture("network", { facilities_included: 0 })) });
    render(<AdminForecast />);
    expect(await screen.findByText("No hospitals yet")).toBeInTheDocument();
  });

  it("shows loading, then an error with retry", async () => {
    routes({ "/api/v1/forecast/model": fail(403, "Permission denied") });
    render(<AdminForecast />);
    expect(await screen.findByText("Network forecast unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
