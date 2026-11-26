import type { AccuracyReport, Campaign } from "./accuracy";
import type { DemoFault, DemoIncident, Detail, Facets, Gabarito, Health, ListFilters, Page } from "./types";

const BASE: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8100";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(BASE + path);
  if (!response.ok) throw new ApiError(response.status, "HTTP " + response.status);
  return (await response.json()) as T;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(BASE + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = "HTTP " + response.status;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      message = "HTTP " + response.status;
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export function startReplay(id: string): Promise<{ id: string; replay_of: string }> {
  return call<{ id: string; replay_of: string }>("POST", "/api/investigations/" + encodeURIComponent(id) + "/replay");
}

export function deleteInvestigation(id: string): Promise<{ deleted: string[] }> {
  return call<{ deleted: string[] }>("DELETE", "/api/investigations/" + encodeURIComponent(id));
}

export function deleteAllInvestigations(): Promise<{ deleted: string[]; count: number }> {
  return call<{ deleted: string[]; count: number }>("DELETE", "/api/investigations");
}

export function fetchAccuracy(): Promise<AccuracyReport> {
  return get<AccuracyReport>("/api/accuracy");
}

export function startCampaign(perFault: number): Promise<Campaign> {
  return call<Campaign>("POST", "/api/campaign", { per_fault: perFault });
}

export function changeCampaign(state: "paused" | "running"): Promise<Campaign> {
  return call<Campaign>("PATCH", "/api/campaign", { state });
}

export function stopCampaign(): Promise<Campaign> {
  return call<Campaign>("DELETE", "/api/campaign");
}

export function fetchHealth(): Promise<Health> {
  return get<Health>("/api/health");
}

export async function fetchDemoIncident(): Promise<DemoIncident | null> {
  const body = await get<{ incident: DemoIncident | null }>("/api/demo/incidents/current");
  return body.incident;
}

export async function fetchDemoFaults(): Promise<DemoFault[]> {
  const body = await get<{ faults: DemoFault[] }>("/api/demo/faults");
  return body.faults;
}

export function startDemoIncident(kind: string): Promise<DemoIncident> {
  return call<DemoIncident>("POST", "/api/demo/incidents", { kind });
}

export function stopDemoIncident(): Promise<DemoIncident> {
  return call<DemoIncident>("DELETE", "/api/demo/incidents/current");
}

export type ListQuery = ListFilters & { limit: number; cursor?: string | null };

export function fetchInvestigations(query: ListQuery): Promise<Page> {
  const params = new URLSearchParams({ limit: String(query.limit) });
  if (query.state) params.set("state", query.state);
  if (query.service) params.set("service", query.service);
  if (query.cursor) params.set("cursor", query.cursor);
  return get<Page>("/api/investigations?" + params.toString());
}

export function fetchFacets(): Promise<Facets> {
  return get<Facets>("/api/investigations/facets");
}

export function fetchInvestigation(id: string): Promise<Detail> {
  return get<Detail>("/api/investigations/" + encodeURIComponent(id));
}

export const streamUrls = {
  global: BASE + "/api/events",
  investigation: (id: string) => BASE + "/api/investigations/" + encodeURIComponent(id) + "/events",
};
