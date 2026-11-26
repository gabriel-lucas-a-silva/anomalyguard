import { useEffect, useState } from "react";
import type { ListFilters, StateFilter } from "./types";

export type Route = { name: "list"; filters: ListFilters } | { name: "detail"; id: string } | { name: "accuracy" };

export const NO_FILTERS: ListFilters = { state: "", service: "" };

const STATES: StateFilter[] = ["running", "completed", "failed"];

export function parseHash(hash: string): Route {
  if (/^#\/acuracia(\?.*)?$/.test(hash)) return { name: "accuracy" };
  const detail = hash.match(/^#\/i\/(INV-\d+)$/);
  if (detail) return { name: "detail", id: detail[1] };
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const state = params.get("state") as StateFilter;
  return { name: "list", filters: { state: STATES.includes(state) ? state : "", service: params.get("service") ?? "" } };
}

export function formatListHash(filters: ListFilters): string {
  const params = new URLSearchParams();
  if (filters.state) params.set("state", filters.state);
  if (filters.service) params.set("service", filters.service);
  const query = params.toString();
  return query ? "#/?" + query : "#/";
}

let lastListHash = "#/";

export function backToList(): string {
  return lastListHash;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      const next = parseHash(window.location.hash);
      if (next.name === "list") lastListHash = formatListHash(next.filters);
      setRoute((current) => {
        if (current.name === "list" && next.name === "list" && current.filters.state === next.filters.state && current.filters.service === next.filters.service) return current;
        return next;
      });
      if (next.name === "detail") window.scrollTo(0, 0);
    };
    onChange();
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
