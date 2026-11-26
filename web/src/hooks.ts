import { useCallback, useEffect, useRef, useState } from "react";
import type { AccuracyReport } from "./accuracy";
import { ApiError, changeCampaign, fetchAccuracy, fetchDemoIncident, fetchFacets, fetchHealth, fetchInvestigation, fetchInvestigations, startCampaign, startDemoIncident, stopCampaign, stopDemoIncident, streamUrls } from "./api";
import { applyGabarito, applyLog, applyNarrativeChunk, applyNarrativeDone, applyNarrativeReset, applyStage, applySuspects, mergePages } from "./reduce";
import { openStream, type ConnectionStatus, type SourceFactory } from "./stream";
import type { DemoIncident, Detail, Facets, ListFilters, Summary } from "./types";

export const PAGE_SIZE = 25;
const MAX_LIMIT = 200;
const RELOAD_DELAY_MS = 400;

export function useInvestigations(filters: ListFilters, factory?: SourceFactory) {
  const [items, setItems] = useState<Summary[]>([]);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const loadedCount = useRef(0);
  const loaded = useRef(false);
  const request = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const { state, service } = filters;

  const load = useCallback(
    async (limit: number) => {
      const mine = ++request.current;
      try {
        const [page, nextFacets] = await Promise.all([fetchInvestigations({ state, service, limit }), fetchFacets()]);
        if (mine !== request.current) return;
        setItems(page.items);
        setTotal(page.total);
        setCursor(page.next_cursor);
        setFacets(nextFacets);
        loadedCount.current = page.items.length;
        loaded.current = true;
        setError(false);
      } catch {
        if (mine !== request.current) return;
        loaded.current = false;
        setError(true);
      } finally {
        if (mine === request.current) setLoading(false);
      }
    },
    [state, service],
  );

  useEffect(() => {
    setLoading(true);
    setItems([]);
    setCursor(null);
    loadedCount.current = 0;
    void load(PAGE_SIZE);
    let wasDown = false;
    const reload = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void load(Math.min(MAX_LIMIT, Math.max(loadedCount.current, PAGE_SIZE))), RELOAD_DELAY_MS);
    };
    const close = openStream(
      streamUrls.global,
      { "investigation.created": reload, "investigation.updated": reload, "investigation.deleted": reload },
      (next) => {
        setStatus(next);
        if (next === "reconnecting") wasDown = true;
        if (next === "live" && (wasDown || !loaded.current)) {
          wasDown = false;
          reload();
        }
      },
      factory,
    );
    return () => {
      close();
      if (timer.current) clearTimeout(timer.current);
      request.current++;
    };
  }, [load, factory]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    const mine = request.current;
    setLoadingMore(true);
    try {
      const page = await fetchInvestigations({ state, service, limit: PAGE_SIZE, cursor });
      if (mine !== request.current) return;
      setItems((current) => {
        const merged = mergePages(current, page.items);
        loadedCount.current = merged.length;
        return merged;
      });
      setCursor(page.next_cursor);
      setTotal(page.total);
    } catch {
      setError(true);
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, loadingMore, state, service]);

  return { items, total, hasMore: cursor !== null, facets, loading, loadingMore, error, status, loadMore };
}

export function useInvestigation(id: string, factory?: SourceFactory) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");

  const refreshGabarito = useCallback(async () => {
    try {
      const fresh = await fetchInvestigation(id);
      setDetail((current) => (current ? applyGabarito(current, { gabarito: fresh.gabarito, summaryGabarito: fresh.summary.gabarito }) : current));
    } catch {
      return;
    }
  }, [id]);

  useEffect(() => {
    let alive = true;
    let close = () => {};
    setDetail(null);
    setLoading(true);
    setNotFound(false);
    setError(false);
    setStatus("connecting");

    const open = () => {
      close = openStream(
        streamUrls.investigation(id),
        {
          snapshot: (data) => {
            setDetail(data as Detail);
            setError(false);
            setLoading(false);
          },
          stage: (data) => {
            const event = data as Parameters<typeof applyStage>[1];
            setDetail((current) => (current ? applyStage(current, event) : current));
            if (event.state === "completed" || event.state === "failed") void refreshGabarito();
          },
          log: (data) => setDetail((current) => (current ? applyLog(current, data as Parameters<typeof applyLog>[1]) : current)),
          suspects: (data) => setDetail((current) => (current ? applySuspects(current, data as Parameters<typeof applySuspects>[1]) : current)),
          "narrative.chunk": (data) => setDetail((current) => (current ? applyNarrativeChunk(current, data as Parameters<typeof applyNarrativeChunk>[1]) : current)),
          "narrative.reset": () => setDetail((current) => (current ? applyNarrativeReset(current) : current)),
          "investigation.deleted": () => {
            close();
            setDetail(null);
            setNotFound(true);
          },
          "narrative.done": (data) => setDetail((current) => (current ? applyNarrativeDone(current, data as Parameters<typeof applyNarrativeDone>[1]) : current)),
        },
        (next) => {
          if (alive) setStatus(next);
        },
        factory,
      );
    };

    (async () => {
      try {
        const data = await fetchInvestigation(id);
        if (!alive) return;
        setDetail(data);
        setLoading(false);
      } catch (e) {
        if (!alive) return;
        setLoading(false);
        if (e instanceof ApiError && e.status === 404) {
          setNotFound(true);
          return;
        }
        setError(true);
      }
      if (alive) open();
    })();

    return () => {
      alive = false;
      close();
    };
  }, [id, factory, refreshGabarito]);

  return { detail, loading, notFound, error, status, refreshGabarito };
}

const DEMO_POLL_MS = 4000;
const DEMO_RETRY_MS = 6000;

export type DemoControl = {
  enabled: boolean;
  incident: DemoIncident | null;
  busy: boolean;
  error: string | null;
  start: (kind: string) => Promise<boolean>;
  stop: () => Promise<boolean>;
  clearError: () => void;
};

export function useDemo(): DemoControl {
  const [enabled, setEnabled] = useState(false);
  const [incident, setIncident] = useState<DemoIncident | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let known = false;
    const tick = async () => {
      let delay: number | null = DEMO_RETRY_MS;
      try {
        if (!known) {
          const health = await fetchHealth();
          if (!alive) return;
          if (!health.demo_mode) return;
          known = true;
          setEnabled(true);
        }
        const current = await fetchDemoIncident();
        if (!alive) return;
        setIncident(current);
        delay = DEMO_POLL_MS;
      } catch {
        delay = DEMO_RETRY_MS;
      }
      if (alive && delay !== null) timer = setTimeout(() => void tick(), delay);
    };
    void tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const run = useCallback(async (action: () => Promise<DemoIncident>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      setIncident(await action());
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível falar com o back-end.");
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    enabled,
    incident,
    busy,
    error,
    start: (kind: string) => run(() => startDemoIncident(kind)),
    stop: () => run(stopDemoIncident),
    clearError: () => setError(null),
  };
}

const ACCURACY_POLL_MS = 15000;

export type AccuracyControl = {
  report: AccuracyReport | null;
  loading: boolean;
  problem: "unavailable" | "offline" | null;
  busy: boolean;
  actionError: string | null;
  start: (perFault: number) => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stop: () => Promise<void>;
};

export function useAccuracy(factory?: SourceFactory): AccuracyControl {
  const [report, setReport] = useState<AccuracyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<"unavailable" | "offline" | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await fetchAccuracy());
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof ApiError && e.status === 404 ? "unavailable" : "offline");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return openStream(streamUrls.global, { "campaign.updated": () => void load(), "accuracy.updated": () => void load() }, () => undefined, factory);
  }, [load, factory]);

  const state = report?.campaign?.state;
  useEffect(() => {
    if (state !== "running" && state !== "paused") return;
    const timer = setInterval(() => void load(), ACCURACY_POLL_MS);
    return () => clearInterval(timer);
  }, [state, load]);

  const act = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      setActionError(null);
      try {
        await action();
        await load();
      } catch (e) {
        setActionError(e instanceof Error ? e.message : "Não foi possível falar com o back-end.");
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  return {
    report,
    loading,
    problem,
    busy,
    actionError,
    start: (perFault) => act(() => startCampaign(perFault)),
    pause: () => act(() => changeCampaign("paused")),
    resume: () => act(() => changeCampaign("running")),
    stop: () => act(() => stopCampaign()),
  };
}
