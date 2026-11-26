import { useState } from "react";
import { casesToCsv, casesToTable, rankLabel, rankTone } from "../accuracy";
import type { AccuracyCase } from "../accuracy";
import { formatDateTime } from "../format";

function download(name: string, content: string) {
  const url = URL.createObjectURL(new Blob(["\ufeff" + content], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function CaseTable({ cases }: { cases: AccuracyCase[] }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(casesToTable(cases));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="case-section" aria-label="Casos">
      <div className="case-head">
        <button className="link" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? "Esconder os casos" : `Ver os ${cases.length} casos`}
        </button>
        <div className="case-tools">
          <button className="btn" onClick={() => void copy()}>
            {copied ? "Copiado" : "Copiar tabela"}
          </button>
          <button className="btn" onClick={() => download("acuracia-casos.csv", casesToCsv(cases))}>
            Baixar CSV
          </button>
        </div>
      </div>
      {open && (
        <ul className="case-rows">
          <li className="case-row case-header" aria-hidden="true">
            <span>Falha</span>
            <span>O TORAI apontou</span>
            <span>Causa real</span>
            <span>Posição</span>
          </li>
          {cases.map((item, index) => {
            const body = (
              <>
                <span className="case-fault">
                  <strong>{item.title}</strong>
                  <span className="muted">{formatDateTime(item.finished_at)}</span>
                </span>
                <span className="case-top">{item.top_service ?? "–"}</span>
                <span className="case-cause">{item.root_cause_service}</span>
                <span className={"case-rank " + rankTone(item)}>{rankLabel(item)}</span>
              </>
            );
            return (
              <li key={(item.id ?? "x") + index}>
                {item.id ? (
                  <a className="case-row" href={"#/i/" + item.id}>
                    {body}
                  </a>
                ) : (
                  <div className="case-row">{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
