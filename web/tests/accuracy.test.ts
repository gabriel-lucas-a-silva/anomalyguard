import { describe, expect, it } from "vitest";
import { casesToCsv, duration, interval, percent, rankLabel, rankTone } from "../src/accuracy";
import type { AccuracyCase } from "../src/accuracy";
import { parseHash } from "../src/route";

function item(over: Partial<AccuracyCase> = {}): AccuracyCase {
  return { id: "INV-0010", kind: "payment_failure", title: "Pagamento falhando", status: "evaluated", top_service: "payment", root_cause_service: "payment", rank: 1, finished_at: "2026-11-23T01:00:00Z", ...over };
}

describe("accuracy formatting", () => {
  it("writes percentages and intervals", () => {
    expect(percent(0.4545)).toBe("45%");
    expect(percent(null)).toBe("–");
    expect(interval({ hits: 15, of: 33, rate: 0.45, low: 0.29, high: 0.62 })).toBe("IC 95%: 29–62%");
    expect(interval({ hits: 0, of: 0, rate: null, low: null, high: null })).toBe("");
  });

  it("writes durations", () => {
    expect(duration(45 * 60)).toBe("45 min");
    expect(duration(7 * 3600 + 20 * 60)).toBe("7 h 20 min");
    expect(duration(12 * 3600)).toBe("12 h");
  });

  it("colours the position of the real cause", () => {
    expect(rankTone(item())).toBe("ok");
    expect(rankTone(item({ rank: 3 }))).toBe("warn");
    expect(rankTone(item({ rank: 9 }))).toBe("error");
    expect(rankTone(item({ status: "no_alert", rank: null }))).toBe("neutral");
    expect(rankLabel(item({ rank: 2 }))).toBe("2º");
    expect(rankLabel(item({ status: "no_alert", rank: null }))).toBe("sem alerta");
  });

  it("exports the cases as CSV with quoted cells", () => {
    const csv = casesToCsv([item({ title: 'Pagamento "falhando"' })]);
    expect(csv.split("\n")).toHaveLength(2);
    expect(csv).toContain('"Pagamento ""falhando"""');
  });
});

describe("route", () => {
  it("recognises the accuracy page with or without a query", () => {
    expect(parseHash("#/acuracia")).toEqual({ name: "accuracy" });
    expect(parseHash("#/acuracia?mock=done")).toEqual({ name: "accuracy" });
  });
});
