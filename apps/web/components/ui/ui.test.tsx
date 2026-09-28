import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Badge } from "./badge";
import { Button } from "./button";
import { SimulatedBadge } from "./simulated-badge";
import { ErrorState, StatusBeacon } from "./states";

describe("Button", () => {
  it("defaults to type=button and primary variant", () => {
    render(<Button>Save</Button>);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn).toHaveAttribute("type", "button");
    expect(btn).toHaveAttribute("data-variant", "primary");
  });

  it("fires onClick and respects disabled", () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Go</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
    rerender(
      <Button onClick={onClick} disabled>
        Go
      </Button>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("SimulatedBadge", () => {
  it("is visibly and accessibly labelled as simulated", () => {
    render(<SimulatedBadge subject="IoT sensor" />);
    const badge = screen.getByLabelText(/IoT sensor: simulated for this prototype/i);
    expect(badge).toHaveTextContent("Simulated");
    expect(badge).toHaveAttribute("data-tone", "simulated");
  });

  it("supports the synthetic data label", () => {
    render(<SimulatedBadge label="Synthetic data" />);
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
  });
});

describe("states", () => {
  it("ErrorState is an alert and shows the request id", () => {
    render(<ErrorState description="Could not load" requestId="abc12345" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Request ID: abc12345");
  });

  it("idle beacon has no pulse ring", () => {
    const { container } = render(<StatusBeacon tone="idle" label="Offline" />);
    expect(container.querySelector(".veyra-beacon")).toBeNull();
  });

  it("Badge renders tone", () => {
    render(<Badge tone="critical">Critical</Badge>);
    expect(screen.getByText("Critical")).toHaveAttribute("data-tone", "critical");
  });
});
