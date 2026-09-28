import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FlowLines } from "@/components/brand/flow-lines";
import { Wordmark } from "@/components/brand/wordmark";
import { publicEnv } from "@/lib/env";

import { DemoRibbon } from "./demo-ribbon";

describe("DemoRibbon", () => {
  it.each(["dev", "test", "demo"] as const)("is shown in %s", (env) => {
    render(<DemoRibbon env={env} />);
    expect(screen.getByRole("note", { name: /demo environment/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /what is simulated/i })).toHaveAttribute(
      "href",
      "/disclosures",
    );
  });

  it("is hidden only in production", () => {
    const { container } = render(<DemoRibbon env="production" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("publicEnv", () => {
  it("never falls back to production for unknown values", () => {
    expect(publicEnv("staging")).toBe("dev");
    expect(publicEnv(undefined)).toBe("dev");
    expect(publicEnv("production")).toBe("production");
  });
});

describe("brand", () => {
  it("wordmark reads VEYRA with tagline", () => {
    render(<Wordmark withTagline />);
    expect(screen.getByText("VEYRA")).toBeInTheDocument();
    expect(screen.getByText("Intelligent Blood Network")).toBeInTheDocument();
  });

  it("flow lines are an accessible image with the full chain", () => {
    render(<FlowLines />);
    const img = screen.getByRole("img", { name: /the veyra network/i });
    for (const label of ["Donors", "Blood bank", "Transport", "Hospital"]) {
      expect(img).toHaveTextContent(label);
    }
    expect(img.querySelectorAll(".veyra-flow-pulse").length).toBe(5);
  });
});
