import { describe, expect, it } from "vitest";
import { ordinal, verdict } from "../src/gabarito";
import type { Gabarito } from "../src/types";

function gab(over: Partial<Gabarito> = {}): Gabarito {
  return { root_cause_service: "payment", fault_kind: "payment_failure", expected_signal: "trace_err", source: "simulation", top_service: "payment", rank: 1, top1: true, top3: true, status: "evaluated", ...over };
}

describe("ordinal", () => {
  it("writes the position with the ordinal sign", () => {
    expect(ordinal(1)).toBe("1º");
    expect(ordinal(12)).toBe("12º");
  });
});

describe("verdict", () => {
  it("is green when the real cause came first", () => {
    const v = verdict(gab());
    expect(v?.tone).toBe("ok");
    expect(v?.title).toBe("Acertou");
  });
  it("is red when the real cause was second, and says who was picked and where the cause landed", () => {
    const v = verdict(gab({ rank: 2, top1: false, top_service: "frontend" }));
    expect(v?.tone).toBe("error");
    expect(v?.title).toBe("Errou · a causa real era payment");
    expect(v?.detail).toBe("O TORAI apontou frontend em 1º, mas a causa real era payment, que ficou em 2º lugar (dentro do Top 3).");
  });
  it("is red outside the Top 3", () => {
    expect(verdict(gab({ rank: 6, top1: false, top3: false, top_service: "cart" }))?.detail).toContain("ficou em 6º lugar, fora do Top 3");
  });
  it("is red when the cause did not appear", () => {
    expect(verdict(gab({ rank: null, top1: false, top3: false, top_service: "cart" }))?.detail).toContain("nem apareceu no ranking");
  });
  it("shows nothing until there is a result to compare", () => {
    expect(verdict(gab({ status: "pending", rank: null, top1: null, top3: null }))).toBeNull();
    expect(verdict(gab({ status: "no_result", rank: null, top1: null, top3: null }))).toBeNull();
  });
});
