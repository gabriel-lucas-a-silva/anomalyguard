import { describe, expect, it } from "vitest";
import { formatListHash, parseHash } from "../src/route";

describe("parseHash", () => {
  it("reads the list route without filters", () => {
    expect(parseHash("")).toEqual({ name: "list", filters: { state: "", service: "" } });
    expect(parseHash("#/")).toEqual({ name: "list", filters: { state: "", service: "" } });
  });

  it("reads the filters from the query", () => {
    expect(parseHash("#/?state=failed&service=cart")).toEqual({ name: "list", filters: { state: "failed", service: "cart" } });
  });

  it("ignores a state that does not exist", () => {
    expect(parseHash("#/?state=quase")).toEqual({ name: "list", filters: { state: "", service: "" } });
  });

  it("decodes a service name", () => {
    expect(parseHash("#/?service=product%20catalog")).toEqual({ name: "list", filters: { state: "", service: "product catalog" } });
  });

  it("reads a detail route", () => {
    expect(parseHash("#/i/INV-0016")).toEqual({ name: "detail", id: "INV-0016" });
  });

  it("does not take a malformed detail id", () => {
    expect(parseHash("#/i/abc")).toEqual({ name: "list", filters: { state: "", service: "" } });
  });
});

describe("formatListHash", () => {
  it("has no query when there are no filters", () => {
    expect(formatListHash({ state: "", service: "" })).toBe("#/");
  });

  it("writes only the filters that are set", () => {
    expect(formatListHash({ state: "failed", service: "" })).toBe("#/?state=failed");
    expect(formatListHash({ state: "", service: "cart" })).toBe("#/?service=cart");
    expect(formatListHash({ state: "completed", service: "cart" })).toBe("#/?state=completed&service=cart");
  });

  it("round-trips through parseHash", () => {
    const filters = { state: "running" as const, service: "product-catalog" };
    expect(parseHash(formatListHash(filters))).toEqual({ name: "list", filters });
  });
});
