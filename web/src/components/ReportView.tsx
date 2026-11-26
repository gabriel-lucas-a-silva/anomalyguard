import { Fragment } from "react";
import { splitCitations } from "../format";
import type { Evidence, Narrative } from "../types";

function Cited({ text, evidence, writing }: { text: string; evidence: Evidence[]; writing: boolean }) {
  return (
    <>
      {splitCitations(text, writing).map((part, index) => {
        if (part.type === "text") return <Fragment key={index}>{part.value}</Fragment>;
        const item = evidence.find((e) => e.id === part.value);
        return (
          <a key={index} className="cite" href={"#evidence-" + part.value} title={item?.text}>
            {part.value}
          </a>
        );
      })}
    </>
  );
}

function Seal({ narrative }: { narrative: Narrative }) {
  if (narrative.state === "writing") return <span className="seal writing">Escrevendo…</span>;
  if (narrative.kind === "llm" && narrative.verified) return <span className="seal ok">Citações verificadas</span>;
  return <span className="seal">Texto automático</span>;
}

export function ReportView({ narrative, evidence }: { narrative: Narrative; evidence: Evidence[] }) {
  const writing = narrative.state === "writing";
  return (
    <section className="report" aria-labelledby="report-title" aria-busy={writing}>
      <div className="report-head">
        <h2 id="report-title">Por que este serviço e não os outros</h2>
        <Seal narrative={narrative} />
      </div>
      {narrative.headline && (
        <p className="headline">
          <Cited text={narrative.headline} evidence={evidence} writing={writing} />
          {writing && narrative.paragraphs.length === 0 && <span className="caret" aria-hidden="true" />}
        </p>
      )}
      {narrative.paragraphs.map((paragraph, index) => (
        <p key={index}>
          <Cited text={paragraph} evidence={evidence} writing={writing} />
          {writing && index === narrative.paragraphs.length - 1 && <span className="caret" aria-hidden="true" />}
        </p>
      ))}
      {narrative.state === "ready" && narrative.kind === "fixed" && narrative.failure_reason && (
        <p className="note">Não foi possível usar a explicação do modelo ({narrative.failure_reason}). Este é o texto automático, montado só com as evidências.</p>
      )}
      <EvidenceList evidence={evidence} />
    </section>
  );
}

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null;
  return (
    <ol className="evidence" aria-label="Evidências">
      {evidence.map((item) => (
        <li key={item.id} id={"evidence-" + item.id}>
          <span className="n">{item.id}</span>
          <span>{item.text}</span>
        </li>
      ))}
    </ol>
  );
}

export function ReportPlaceholder({ message, busy = false }: { message: string; busy?: boolean }) {
  return (
    <section className="report" aria-busy={busy}>
      <div className="report-head">
        <h2>Por que este serviço e não os outros</h2>
        {busy && <span className="seal writing">Escrevendo…</span>}
      </div>
      <p className="muted">{message}</p>
    </section>
  );
}
