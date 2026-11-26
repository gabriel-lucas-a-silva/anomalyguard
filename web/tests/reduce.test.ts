import { describe, expect, it } from "vitest";
import { applyGabarito, applyLog, applyStage, applySuspects, mergePages } from "../src/reduce";
import type { Detail, Summary } from "../src/types";

function summary(id: string, receivedAt: string, state: Summary["state"] = "waiting"): Summary {
  return { id, alert_name: "FrontendHighErrorRate", service: "frontend", received_at: receivedAt, state, stage: 1, top_suspect: null, grouped_alerts: 1, resolved_before_analysis: false, replay_of: null, gabarito: null };
}

function detail(): Detail {
  return { summary: summary("INV-0001", "2026-11-22T16:27:05Z"), gabarito: null, replayable: false, failure_reason: null, log: [], suspects: [], narrative: null, evidence: [], limitations: [], timings_ms: {}, missing_sources: [] };
}

describe("applyStage", () => {
  it("moves the investigation to the new state and stage", () => {
    const next = applyStage(detail(), { state: "collecting", stage: 2 });
    expect(next.summary.state).toBe("collecting");
    expect(next.summary.stage).toBe(2);
  });
});

describe("applyLog", () => {
  const entry = { at: "2026-11-22T16:31:22.224863+00:00", tag: "coleta", message: "Coletando métricas e logs do ambiente" };

  it("appends a new log line", () => {
    expect(applyLog(detail(), entry).log).toEqual([entry]);
  });

  it("ignores a line the snapshot already has", () => {
    const once = applyLog(detail(), entry);
    expect(applyLog(once, entry).log).toHaveLength(1);
  });
});

describe("applySuspects", () => {
  const suspects = [
    { rank: 1, service: "payment", share: 0.2931, torai_score: 0.2931, signal: "Erros nos traces", detail: "x", evidence_ids: [] },
    { rank: 2, service: "ad", share: 0.17, torai_score: 0.17, signal: "Disco", detail: "y", evidence_ids: [] },
  ];

  it("stores the suspects and the top suspect on the summary", () => {
    const next = applySuspects(detail(), { suspects });
    expect(next.suspects).toHaveLength(2);
    expect(next.summary.top_suspect).toEqual({ service: "payment", share: 0.2931 });
  });

  it("clears the top suspect when there are none", () => {
    expect(applySuspects(detail(), { suspects: [] }).summary.top_suspect).toBeNull();
  });
});

import { applyNarrativeChunk, applyNarrativeDone, applyNarrativeReset } from "../src/reduce";

describe("narrative events", () => {
  it("builds the headline and the paragraphs from the chunks, in order", () => {
    let next = detail();
    next = applyNarrativeChunk(next, { paragraph: 0, text: "payment é " });
    next = applyNarrativeChunk(next, { paragraph: 0, text: "o suspeito." });
    next = applyNarrativeChunk(next, { paragraph: 1, text: "Veja [1]." });
    expect(next.narrative?.state).toBe("writing");
    expect(next.narrative?.headline).toBe("payment é o suspeito.");
    expect(next.narrative?.paragraphs).toEqual(["Veja [1]."]);
  });

  it("fills the gap when a later paragraph arrives first", () => {
    const next = applyNarrativeChunk(detail(), { paragraph: 2, text: "terceiro" });
    expect(next.narrative?.paragraphs).toEqual(["", "terceiro"]);
  });

  it("discards the partial text on a reset and starts over", () => {
    let next = applyNarrativeChunk(detail(), { paragraph: 0, text: "texto velho" });
    next = applyNarrativeReset(next);
    expect(next.narrative).toBeNull();
    next = applyNarrativeChunk(next, { paragraph: 0, text: "texto novo" });
    expect(next.narrative?.headline).toBe("texto novo");
  });

  it("does not touch a finished narrative on a reset", () => {
    const done = applyNarrativeDone(detail(), { narrative: { state: "ready", kind: "llm", verified: true, headline: "h", paragraphs: [], model: "m", failure_reason: null } });
    expect(applyNarrativeReset(done).narrative?.state).toBe("ready");
  });

  it("replaces the partial text with the final narrative", () => {
    const partial = applyNarrativeChunk(detail(), { paragraph: 0, text: "parcial" });
    const final = { state: "ready" as const, kind: "fixed" as const, verified: null, headline: "fixo", paragraphs: ["p"], model: null, failure_reason: "x" };
    const next = applyNarrativeDone(partial, { narrative: final });
    expect(next.narrative).toEqual(final);
  });

  it("keeps the evidence and limitations that come with the suspects", () => {
    const next = applySuspects(detail(), { suspects: [], evidence: [{ id: 1, service: "payment", text: "t" }], limitations: ["Sem logs para ad."] });
    expect(next.evidence).toHaveLength(1);
    expect(next.limitations).toEqual(["Sem logs para ad."]);
  });
});


describe("mergePages", () => {
  const a = summary("INV-0003", "2026-11-22T16:00:00Z");
  const b = summary("INV-0002", "2026-11-22T12:00:00Z");
  const c = summary("INV-0001", "2026-11-22T10:00:00Z");

  it("appends the older page after the loaded ones", () => {
    expect(mergePages([a, b], [c]).map((s) => s.id)).toEqual(["INV-0003", "INV-0002", "INV-0001"]);
  });

  it("does not repeat an item that is already loaded", () => {
    expect(mergePages([a, b], [b, c]).map((s) => s.id)).toEqual(["INV-0003", "INV-0002", "INV-0001"]);
  });

  it("keeps the loaded version of a repeated item", () => {
    const loaded = summary("INV-0002", "2026-11-22T12:00:00Z", "completed");
    expect(mergePages([loaded], [summary("INV-0002", "2026-11-22T12:00:00Z", "waiting")])[0].state).toBe("completed");
  });

  it("keeps the order the server gave, without sorting again", () => {
    const sameSecondFirst = summary("INV-0009", "2026-11-22T16:27:05Z");
    const sameSecondSecond = summary("INV-0011", "2026-11-22T16:27:05Z");
    expect(mergePages([sameSecondFirst], [sameSecondSecond]).map((s) => s.id)).toEqual(["INV-0009", "INV-0011"]);
  });

});


describe("applyGabarito", () => {
  const full = { root_cause_service: "payment", rank: 2, top1: false, top3: true, status: "evaluated" as const, fault_kind: "payment_failure", expected_signal: "trace_err", source: "simulation" as const };
  const compact = { root_cause_service: "payment", rank: 2, top1: false, top3: true, status: "evaluated" as const };

  it("updates the gabarito in the detail and in its summary without touching the rest", () => {
    const base = applyLog(detail(), { at: "2026-11-22T16:31:22Z", tag: "coleta", message: "x" });
    const next = applyGabarito(base, { gabarito: full, summaryGabarito: compact });
    expect(next.gabarito).toEqual(full);
    expect(next.summary.gabarito).toEqual(compact);
    expect(next.log).toHaveLength(1);
  });

  it("clears the gabarito when it was removed", () => {
    const labeled = applyGabarito(detail(), { gabarito: full, summaryGabarito: compact });
    const cleared = applyGabarito(labeled, { gabarito: null, summaryGabarito: null });
    expect(cleared.gabarito).toBeNull();
    expect(cleared.summary.gabarito).toBeNull();
  });
});
