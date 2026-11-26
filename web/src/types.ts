export type State = "received" | "waiting" | "collecting" | "preparing" | "analyzing" | "explaining" | "completed" | "failed";

export type TopSuspect = {
  service: string;
  share: number;
};

export type GabaritoStatus = "evaluated" | "pending" | "no_result";

export type GabaritoCompact = {
  root_cause_service: string;
  rank: number | null;
  top1: boolean | null;
  top3: boolean | null;
  status: GabaritoStatus;
};

export type Gabarito = GabaritoCompact & {
  fault_kind: string;
  expected_signal: string | null;
  source: "simulation";
  top_service: string | null;
};

export type Summary = {
  id: string;
  alert_name: string;
  service: string;
  received_at: string;
  state: State;
  stage: number;
  top_suspect: TopSuspect | null;
  grouped_alerts: number;
  resolved_before_analysis: boolean;
  replay_of: string | null;
  gabarito: GabaritoCompact | null;
};

export type Suspect = {
  rank: number;
  service: string;
  share: number;
  torai_score: number;
  signal: string;
  detail: string;
  evidence_ids: number[];
};

export type LogLine = {
  at: string;
  tag: string;
  message: string;
};

export type Evidence = {
  id: number;
  service: string;
  text: string;
};

export type Narrative = {
  state: "writing" | "ready";
  kind: "llm" | "fixed";
  verified: boolean | null;
  headline: string;
  paragraphs: string[];
  model: string | null;
  failure_reason: string | null;
  ttft_ms?: number | null;
  total_ms?: number | null;
  attempts?: number;
};

export type Detail = {
  summary: Summary;
  gabarito: Gabarito | null;
  replayable: boolean;
  failure_reason: string | null;
  log: LogLine[];
  suspects: Suspect[];
  narrative: Narrative | null;
  evidence: Evidence[];
  limitations: string[];
  timings_ms: Record<string, number>;
  missing_sources: string[];
};

export type StateFilter = "" | "running" | "completed" | "failed";

export type ListFilters = {
  state: StateFilter;
  service: string;
};

export type Page = {
  items: Summary[];
  next_cursor: string | null;
  total: number;
};

export type Facets = {
  services: { service: string; count: number }[];
  states: { running: number; completed: number; failed: number };
};

export type DemoFault = {
  kind: string;
  title: string;
  description: string;
  affected_service: string;
  alert: string;
};

export type DemoIncident = {
  id: number;
  kind: string;
  title: string | null;
  state: "active" | "finished" | "stopped" | "failed";
  started_at: string;
  ends_at: string;
  finished_at: string | null;
  failure_reason: string | null;
  investigation_id: string | null;
};

export type Health = {
  status: string;
  demo_mode: boolean;
  narrator: boolean;
};
