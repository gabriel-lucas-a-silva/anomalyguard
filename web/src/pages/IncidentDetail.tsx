import { useState } from "react";
import { GabaritoPanel } from "../components/GabaritoPanel";
import { LiveBadge } from "../components/LiveBadge";
import { LogView } from "../components/LogView";
import { DeleteButton } from "../components/DeleteButton";
import { ReplayButton } from "../components/ReplayButton";
import { Notes } from "../components/Notes";
import { ReportPlaceholder, ReportView } from "../components/ReportView";
import { StatusPill } from "../components/StatusPill";
import { Stepper } from "../components/Stepper";
import { SuspectCard, SuspectPlaceholder } from "../components/SuspectCard";
import { formatDateTime, isRunning } from "../format";
import { useInvestigation } from "../hooks";
import { backToList } from "../route";
import type { Detail } from "../types";

function Back() {
  return (
    <a className="back" href={backToList()}>
      ← Investigações
    </a>
  );
}

function Explanation({ detail, running }: { detail: Detail; running: boolean }) {
  if (detail.narrative) return <ReportView narrative={detail.narrative} evidence={detail.evidence} />;
  if (detail.summary.state === "explaining") return <ReportPlaceholder message="O modelo está lendo as evidências..." busy />;
  if (running) return <ReportPlaceholder message="A explicação aparece aqui quando a análise terminar." />;
  return <ReportPlaceholder message="Esta investigação é anterior à explicação em linguagem natural." />;
}

export function IncidentDetail({ id }: { id: string }) {
  const { detail, loading, notFound, error, status, refreshGabarito } = useInvestigation(id);
  const [showLog, setShowLog] = useState(false);

  if (notFound) {
    return (
      <div className="page">
        <Back />
        <p className="empty">Investigação não encontrada.</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="page">
        <Back />
        {error ? (
          <p className="notice" role="alert">
            Não foi possível carregar a investigação. Vou tentar de novo assim que o back-end voltar.
          </p>
        ) : (
          loading && <p className="empty">Carregando...</p>
        )}
      </div>
    );
  }

  const { summary } = detail;
  const running = isRunning(summary.state);
  const failed = summary.state === "failed";

  const logSection = (
    <section aria-labelledby="log-title">
      <div className="log-head">
        <h2 id="log-title" className="section-title">
          Registro do processamento
        </h2>
        {!running && (
          <button className="link" onClick={() => setShowLog((v) => !v)}>
            {showLog ? "Ocultar" : "Mostrar"}
          </button>
        )}
      </div>
      {(running || showLog) && <LogView lines={detail.log} running={running} height={running ? 320 : 280} />}
    </section>
  );

  return (
    <div className="page">
      <Back />
      <div className="detail-head">
        <div className="detail-meta">
          <span className="eyebrow">{summary.id}</span>
          <StatusPill summary={summary} />
          <LiveBadge status={status} />
        </div>
        <div className="detail-title">
          <div>
            <h1>{summary.alert_name}</h1>
            <p className="muted">
              alerta no {summary.service} · {formatDateTime(summary.received_at)}
            </p>
          </div>
          <div className="toolbar">
            {detail.replayable && <ReplayButton id={summary.id} />}
            {!running && <DeleteButton id={summary.id} />}
          </div>
        </div>
      </div>

      <Notes summary={summary} />

      <GabaritoPanel detail={detail} />

      <Stepper summary={summary} />

      {failed && (
        <p className="notice" role="alert">
          A investigação não terminou: {detail.failure_reason}
        </p>
      )}

      {running && logSection}

      {!failed && (
        <section aria-labelledby="suspects-title">
          <h2 id="suspects-title" className="section-title">
            Serviços com mais chance de ser a causa
          </h2>
          <div className="suspects">
            {detail.suspects.length > 0
              ? detail.suspects.map((s) => <SuspectCard key={s.service} suspect={s} />)
              : [1, 2, 3].map((rank) => <SuspectPlaceholder key={rank} rank={rank} />)}
          </div>
          <p className="footnote">
            A porcentagem é a parte da anomalia total que o TORAI atribui a cada serviço. Os três não somam 100% porque o resto fica espalhado pelos
            outros serviços.
          </p>
        </section>
      )}

      {!failed && <Explanation detail={detail} running={running} />}

      {detail.limitations.length > 0 && !failed && (
        <section aria-labelledby="limits-title">
          <h2 id="limits-title" className="section-title">
            Limitações
          </h2>
          <ul className="limits">
            {detail.limitations.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </section>
      )}

      {!running && logSection}
    </div>
  );
}
