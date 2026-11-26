import { describe, expect, it } from "vitest";
import { formatPercent, isRunning, isTerminal, parseInstant } from "../src/format";

describe("formatPercent", () => {
  it("rounds the torai score to a whole percentage", () => {
    expect(formatPercent(0.2783)).toBe("28");
    expect(formatPercent(0.5)).toBe("50");
    expect(formatPercent(1)).toBe("100");
  });

  it("shows a tiny positive share as less than one percent", () => {
    expect(formatPercent(0.004)).toBe("<1");
  });

  it("shows zero as zero", () => {
    expect(formatPercent(0)).toBe("0");
  });
});

describe("parseInstant", () => {
  it("accepts the microseconds the back-end sends", () => {
    expect(parseInstant("2026-11-22T02:16:23.123456+00:00").toISOString()).toBe("2026-11-22T02:16:23.123Z");
  });

  it("accepts a plain UTC timestamp", () => {
    expect(parseInstant("2026-11-21T14:03:10Z").toISOString()).toBe("2026-11-21T14:03:10.000Z");
  });
});

describe("investigation states", () => {
  it("treats completed and failed as terminal", () => {
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("analyzing")).toBe(false);
  });

  it("is running while it has not finished", () => {
    expect(isRunning("collecting")).toBe(true);
    expect(isRunning("completed")).toBe(false);
  });
});

import { splitCitations } from "../src/format";

describe("splitCitations", () => {
  it("separates the text from the evidence numbers", () => {
    expect(splitCitations("falhou [1] e depois [2].")).toEqual([
      { type: "text", value: "falhou " },
      { type: "cite", value: 1 },
      { type: "text", value: " e depois " },
      { type: "cite", value: 2 },
      { type: "text", value: "." },
    ]);
  });

  it("returns only text when there are no citations", () => {
    expect(splitCitations("sem citações")).toEqual([{ type: "text", value: "sem citações" }]);
  });

  it("hides a citation that is still being written", () => {
    expect(splitCitations("erros [1] e logs [", true)).toEqual([
      { type: "text", value: "erros " },
      { type: "cite", value: 1 },
      { type: "text", value: " e logs " },
    ]);
    expect(splitCitations("logs [4", true).at(-1)).toEqual({ type: "text", value: "logs " });
  });

  it("keeps a trailing bracket when the text is final", () => {
    expect(splitCitations("fim [", false)).toEqual([{ type: "text", value: "fim [" }]);
  });
});
