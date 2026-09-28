import { describe, expect, it } from "vitest";

import { toFailure } from "./problem";
import { homeFor, safeNext } from "./roles";
import {
  DEMO_VERIFICATION_DISCLAIMER,
  indianMobileDigits,
  passwordStrength,
  validate,
  validators,
} from "./validation";

describe("validation (mirrors the API rules)", () => {
  it("keeps the mandatory demo disclaimer verbatim", () => {
    expect(DEMO_VERIFICATION_DISCLAIMER).toBe(
      "Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP.",
    );
  });

  it.each([
    ["9876543210", "9876543210"],
    ["98765 43210", "9876543210"],
    ["+91 98765-43210", "9876543210"],
    ["919876543210", "9876543210"],
    ["09876543210", "9876543210"],
  ])("normalises mobile %s", (raw, digits) => {
    expect(indianMobileDigits(raw)).toBe(digits);
  });

  it.each(["12345", "5876543210", "+1 415 555 0100"])("rejects mobile %s", (raw) => {
    expect(indianMobileDigits(raw)).toBeNull();
  });

  it("validates fields", () => {
    expect(validators.pin_code("700016")).toBeNull();
    expect(validators.pin_code("012345")).not.toBeNull();
    expect(validators.full_name("A. P. J. Abdul Kalam")).toBeNull();
    expect(validators.full_name("R2D2")).not.toBeNull();
    expect(validators.email("arpan@example.in")).toBeNull();
    expect(validators.email("a@b")).not.toBeNull();
    const errors = validate({ email: "bad", password: "short" }, ["email", "password"] as const);
    expect(Object.keys(errors).sort()).toEqual(["email", "password"]);
  });

  it("gives an honest, length-driven strength hint", () => {
    expect(passwordStrength("short").score).toBe(0);
    expect(passwordStrength("abcdefghij").score).toBe(1);
    expect(passwordStrength("correct horse battery staple").score).toBe(3);
  });
});

describe("roles", () => {
  it("maps roles to their home", () => {
    expect(homeFor("DONOR")).toBe("/donor");
    expect(homeFor("BLOOD_BANK")).toBe("/blood-bank");
    expect(homeFor("UNKNOWN")).toBe("/");
  });

  it("only allows same-site relative redirects", () => {
    expect(safeNext("/donor")).toBe("/donor");
    for (const bad of ["https://evil.example", "//evil.example", "/\\evil", null, ""]) {
      expect(safeNext(bad)).toBeNull();
    }
  });
});

describe("problem handling", () => {
  it("maps 422 problems to field errors with a summary", () => {
    const f = toFailure({
      type: "t",
      title: "Validation failed",
      status: 422,
      code: "validation_error",
      detail: "Request is invalid",
      request_id: "r1",
      errors: [{ loc: ["body", "email"], msg: "Value error, Enter a valid email address", type: "value_error" }],
    });
    expect(f.fields).toEqual({ email: "Enter a valid email address" });
    expect(f.message).toBe("Please correct the highlighted fields.");
  });

  it("uses the API detail for other problems and a friendly fallback otherwise", () => {
    const locked = toFailure({ type: "t", title: "x", status: 423, code: "account_locked", detail: "Too many attempts.", request_id: null });
    expect(locked.message).toBe("Too many attempts.");
    expect(toFailure(undefined).problem.code).toBe("network_error");
    expect(toFailure("<html>", new Response("", { status: 502 })).problem.status).toBe(502);
  });
});
