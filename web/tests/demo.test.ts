import { describe, expect, it } from "vitest";
import { countdown, describeIncident, remainingSeconds, shouldShow } from "../src/demo";
import type { DemoIncident } from "../src/types";

function incident(over: Partial<DemoIncident> = {}): DemoIncident {
  return {
    id: 1,
    kind: "payment_failure",
    title: "Pagamento falhando",
    state: "active",
    started_at: "2026-11-22T17:09:45Z",
    ends_at: "2026-11-22T17:16:45Z",
    finished_at: null,
    failure_reason: null,
    investigation_id: null,
    ...over,
  };
}

const AT = (iso: string) => Date.parse(iso);

describe("countdown", () => {
  it("writes minutes and seconds", () => {
    expect(countdown(0)).toBe("0:00");
    expect(countdown(65)).toBe("1:05");
    expect(countdown(420)).toBe("7:00");
  });
});

describe("remainingSeconds", () => {
  it("counts down to the end of the simulation", () => {
    expect(remainingSeconds(incident(), AT("2026-11-22T17:12:45Z"))).toBe(240);
  });

  it("never goes below zero", () => {
    expect(remainingSeconds(incident(), AT("2026-11-22T17:30:00Z"))).toBe(0);
  });
});

describe("describeIncident", () => {
  it("says it is waiting for the alert before the investigation exists", () => {
    const message = describeIncident(incident());
    expect(message.tone).toBe("active");
    expect(message.detail).toContain("Aguardando o alerta real");
  });

  it("explains the likely cause when the alert is late and no investigation was opened", () => {
    const late = describeIncident(incident(), AT("2026-11-22T17:15:46Z"));
    expect(late.detail).toContain("Passaram mais de 5 minutos");
    expect(late.detail).toContain("alerta anterior ainda pode estar ativo");
    expect(describeIncident(incident(), AT("2026-11-22T17:14:44Z")).detail).toContain("Aguardando o alerta real");
  });

  it("does not warn about a late alert once the investigation exists", () => {
    expect(describeIncident(incident({ investigation_id: "INV-0028" }), AT("2026-11-22T17:30:00Z")).detail).toContain("O alerta real disparou");
  });

  it("says the alert fired once the investigation is linked", () => {
    expect(describeIncident(incident({ investigation_id: "INV-0028" })).detail).toContain("O alerta real disparou");
  });

  it("tells that it ended by itself or was stopped", () => {
    expect(describeIncident(incident({ state: "finished" })).title).toBe("Simulação encerrada");
    expect(describeIncident(incident({ state: "stopped" })).title).toBe("Simulação interrompida");
  });

  it("warns, as an error, that the fault may still be on when it could not be turned off", () => {
    const message = describeIncident(incident({ state: "failed", failure_reason: "o Demo está inacessível" }));
    expect(message.tone).toBe("error");
    expect(message.detail).toContain("o Demo está inacessível");
    expect(message.detail).toContain("Desligue a falha");
  });
});

describe("shouldShow", () => {
  it("shows nothing without an incident", () => {
    expect(shouldShow(null, 0, null)).toBe(false);
  });

  it("always shows an active incident and one that failed to turn off", () => {
    expect(shouldShow(incident(), AT("2026-11-22T17:10:00Z"), 1)).toBe(true);
    expect(shouldShow(incident({ state: "failed", finished_at: "2026-11-22T17:16:45Z" }), AT("2026-11-22T20:00:00Z"), 1)).toBe(true);
  });

  it("shows a finished incident for a while after it ended", () => {
    const done = incident({ state: "finished", finished_at: "2026-11-22T17:16:45Z" });
    expect(shouldShow(done, AT("2026-11-22T17:20:00Z"), null)).toBe(true);
    expect(shouldShow(done, AT("2026-11-22T17:40:00Z"), null)).toBe(false);
  });

  it("hides a finished incident the user dismissed", () => {
    const done = incident({ state: "finished", finished_at: "2026-11-22T17:16:45Z" });
    expect(shouldShow(done, AT("2026-11-22T17:20:00Z"), 1)).toBe(false);
    expect(shouldShow(done, AT("2026-11-22T17:20:00Z"), 2)).toBe(true);
  });
});
