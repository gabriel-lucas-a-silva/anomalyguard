import type { Detail, Evidence, Gabarito, LogLine, Narrative, Summary, Suspect } from "./types";

export function mergePages(existing: Summary[], incoming: Summary[]): Summary[] {
  const known = new Set(existing.map((item) => item.id));
  return [...existing, ...incoming.filter((item) => !known.has(item.id))];
}

export function applyStage(detail: Detail, event: { state: Summary["state"]; stage: number }): Detail {
  return { ...detail, summary: { ...detail.summary, state: event.state, stage: event.stage } };
}

export function applyLog(detail: Detail, entry: LogLine): Detail {
  const seen = detail.log.some((line) => line.at === entry.at && line.message === entry.message);
  return seen ? detail : { ...detail, log: [...detail.log, entry] };
}

export function applySuspects(detail: Detail, event: { suspects: Suspect[]; evidence?: Evidence[]; limitations?: string[] }): Detail {
  const top = event.suspects[0];
  return {
    ...detail,
    suspects: event.suspects,
    evidence: event.evidence ?? detail.evidence,
    limitations: event.limitations ?? detail.limitations,
    summary: { ...detail.summary, top_suspect: top ? { service: top.service, share: top.share } : null },
  };
}

function writing(): Narrative {
  return { state: "writing", kind: "llm", verified: null, headline: "", paragraphs: [], model: null, failure_reason: null };
}

export function applyNarrativeChunk(detail: Detail, event: { paragraph: number; text: string }): Detail {
  const base = detail.narrative && detail.narrative.state === "writing" ? detail.narrative : writing();
  const blocks = [base.headline, ...base.paragraphs];
  while (blocks.length <= event.paragraph) blocks.push("");
  blocks[event.paragraph] += event.text;
  return { ...detail, narrative: { ...base, headline: blocks[0], paragraphs: blocks.slice(1) } };
}

export function applyNarrativeReset(detail: Detail): Detail {
  return detail.narrative && detail.narrative.state === "writing" ? { ...detail, narrative: null } : detail;
}

export function applyNarrativeDone(detail: Detail, event: { narrative: Narrative }): Detail {
  return { ...detail, narrative: event.narrative };
}

export function applyGabarito(detail: Detail, fresh: { gabarito: Gabarito | null; summaryGabarito: Summary["gabarito"] }): Detail {
  return { ...detail, gabarito: fresh.gabarito, summary: { ...detail.summary, gabarito: fresh.summaryGabarito } };
}
