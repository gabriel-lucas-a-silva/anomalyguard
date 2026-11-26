import { DeleteAllButton } from "../components/DeleteAllButton";
import { ChartIcon } from "../components/Icons";
import { LiveBadge } from "../components/LiveBadge";
import { StatusPill } from "../components/StatusPill";
import { formatDateTime, formatPercent } from "../format";
import { useInvestigations } from "../hooks";
import { NO_FILTERS, formatListHash } from "../route";
import type { ListFilters, StateFilter } from "../types";

type Option = { key: StateFilter; label: string };

const OPTIONS: Option[] = [
  { key: "", label: "Todas" },
  { key: "running", label: "Em andamento" },
  { key: "completed", label: "Concluídas" },
  { key: "failed", label: "Falharam" },
];

function go(filters: ListFilters) {
  window.location.hash = formatListHash(filters);
}

export function IncidentList({ filters }: { filters: ListFilters }) {
  const { items, total, hasMore, facets, loading, loadingMore, error, status, loadMore } = useInvestigations(filters);
  const active = filters.state !== "" || filters.service !== "";
  const counts: Record<StateFilter, number | null> = {
    "": facets ? facets.states.running + facets.states.completed + facets.states.failed : null,
    running: facets?.states.running ?? null,
    completed: facets?.states.completed ?? null,
    failed: facets?.states.failed ?? null,
  };
  const services = facets?.services ?? [];
  const knownService = filters.service === "" || services.some((s) => s.service === filters.service);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Investigações</h1>
          <p className="muted">
            {active ? `${total} com estes filtros` : `${total} no total`} · <LiveBadge status={status} />
          </p>
        </div>
        <div className="filters">
          <div className="segmented" role="tablist" aria-label="Estado">
            {OPTIONS.map((option) => (
              <button key={option.key} role="tab" aria-selected={filters.state === option.key} onClick={() => go({ ...filters, state: option.key })}>
                {option.label}
                {counts[option.key] !== null && <span className="count">{counts[option.key]}</span>}
              </button>
            ))}
          </div>
          <label className="select">
            <span className="sr-only">Serviço</span>
            <select value={filters.service} onChange={(event) => go({ ...filters, service: event.target.value })}>
              <option value="">Todos os serviços</option>
              {!knownService && <option value={filters.service}>{filters.service}</option>}
              {services.map((s) => (
                <option key={s.service} value={s.service}>
                  {s.service} ({s.count})
                </option>
              ))}
            </select>
          </label>
          {active && (
            <button className="link clear" onClick={() => go(NO_FILTERS)}>
              Limpar filtros
            </button>
          )}
          <a className="btn" href="#/acuracia">
            <ChartIcon />
            <span>Acurácia</span>
          </a>
          {facets && <DeleteAllButton finished={facets.states.completed + facets.states.failed} running={facets.states.running} />}
        </div>
      </div>


      {error && (
        <p className="notice" role="alert">
          Não foi possível falar com o back-end. Vou tentar de novo assim que ele voltar.
        </p>
      )}

      {items.length > 0 && (
        <ul className="rows">
          {items.map((item) => (
            <li key={item.id}>
              <a className="row" href={"#/i/" + item.id}>
                <div className="when">
                  <span className="id">{item.id}</span>
                  <span className="muted">{formatDateTime(item.received_at)}</span>
                </div>
                <div className="what">
                  <strong>{item.alert_name}</strong>
                  <span className="muted">
                    alerta no {item.service}
                    {item.replay_of && ` · reprodução de ${item.replay_of}`}
                  </span>
                </div>
                <div className="state">
                  <StatusPill summary={item} />
                </div>
                <div className="result">
                  <div className="result-top">
                    {item.top_suspect ? (
                      <>
                        <span className="svc">{item.top_suspect.service}</span>
                        <span className="pct">{formatPercent(item.top_suspect.share)}%</span>
                      </>
                    ) : (
                      <span className="muted">{item.state === "failed" ? "sem resultado" : "analisando..."}</span>
                    )}
                  </div>
                </div>
                <span className="chev" aria-hidden="true">
                  ›
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="empty">
          <p>{active ? "Nenhuma investigação com esses filtros." : "Ainda não há investigações."}</p>
          {active && (
            <button className="link" onClick={() => go(NO_FILTERS)}>
              Limpar filtros
            </button>
          )}
        </div>
      )}

      {items.length > 0 && (
        <div className="more">
          <span className="muted">
            Mostrando {items.length} de {total}
          </span>
          {hasMore && (
            <button className="btn" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore ? "Carregando..." : "Carregar mais"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
