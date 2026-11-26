export type CaseStatus = "evaluated" | "no_alert" | "failed";

export type AccuracyCase = {
  id: string | null;
  kind: string;
  title: string;
  status: CaseStatus;
  top_service: string | null;
  root_cause_service: string;
  rank: number | null;
  finished_at: string;
};

export type Rate = {
  hits: number;
  of: number;
  rate: number | null;
  low: number | null;
  high: number | null;
};

export type FaultAccuracy = {
  kind: string;
  title: string;
  planned: number;
  evaluated: number;
  no_alert: number;
  failed: number;
  top1: Rate;
  top3: Rate;
};

export type AccuracySummary = {
  cases: number;
  evaluated: number;
  no_alert: number;
  failed: number;
  top1: Rate;
  top3: Rate;
  detection: Rate;
  mean_rank: number | null;
};

export type CampaignPhase = "calm_wait" | "fault_on" | "analyzing";

export type Campaign = {
  id: number;
  state: "running" | "paused" | "finished" | "stopped";
  per_fault: number;
  total: number;
  done: number;
  started_at: string;
  eta_s: number | null;
  pause_reason: string | null;
  current: { kind: string; title: string; phase: CampaignPhase; detail: string } | null;
};

export type AccuracyReport = {
  summary: AccuracySummary;
  by_fault: FaultAccuracy[];
  cases: AccuracyCase[];
  campaign: Campaign | null;
};

export const SIZES = [
  { key: 4, label: "Rápida", hours: 4 },
  { key: 8, label: "Padrão", hours: 8 },
  { key: 12, label: "Completa", hours: 12 },
] as const;

export function percent(rate: number | null): string {
  return rate === null ? "–" : `${Math.round(rate * 100)}%`;
}

export function interval(rate: Rate): string {
  if (rate.low === null || rate.high === null) return "";
  return `IC 95%: ${Math.round(rate.low * 100)}–${Math.round(rate.high * 100)}%`;
}

export function ordinal(rank: number): string {
  return `${rank}º`;
}

export function rankTone(item: AccuracyCase): "ok" | "warn" | "error" | "neutral" {
  if (item.status !== "evaluated" || item.rank === null) return "neutral";
  if (item.rank === 1) return "ok";
  return item.rank <= 3 ? "warn" : "error";
}

export function rankLabel(item: AccuracyCase): string {
  if (item.status === "no_alert") return "sem alerta";
  if (item.status === "failed") return "falhou";
  return item.rank === null ? "fora do ranking" : ordinal(item.rank);
}

export function duration(seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export function casesToCsv(cases: AccuracyCase[]): string {
  const head = ["falha", "situacao", "apontado_pelo_torai", "causa_real", "posicao_da_causa_real", "investigacao", "concluida_em"];
  const rows = cases.map((c) => [c.title, c.status, c.top_service ?? "", c.root_cause_service, c.rank ?? "", c.id ?? "", c.finished_at]);
  return [head, ...rows].map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
}

export function casesToTable(cases: AccuracyCase[]): string {
  const head = ["Falha", "Situação", "TORAI apontou", "Causa real", "Posição"];
  const rows = cases.map((c) => [c.title, c.status === "evaluated" ? "avaliado" : c.status === "no_alert" ? "sem alerta" : "falhou", c.top_service ?? "–", c.root_cause_service, c.rank === null ? "–" : ordinal(c.rank)]);
  return [head, ...rows].map((row) => row.join("\t")).join("\n");
}
