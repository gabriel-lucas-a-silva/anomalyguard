import { CampaignCard } from "../components/CampaignCard";
import { CaseTable } from "../components/CaseTable";
import { FaultAccuracyList } from "../components/FaultAccuracyList";
import { RateCard } from "../components/RateCard";
import { useAccuracy } from "../hooks";

export function Accuracy() {
  const control = useAccuracy();
  const { report, loading, problem } = control;

  return (
    <div className="page">
      <a className="back" href="#/">
        ← Investigações
      </a>

      <div className="acc-head">
        <div>
          <h1>Acurácia do TORAI</h1>
          <p className="muted">Taxa de acerto sobre os incidentes simulados em campanha, comparando o ranking com a causa real.</p>
        </div>
      </div>

      {loading && <p className="empty">Carregando...</p>}
      {problem === "unavailable" && <p className="notice">A campanha de acurácia só funciona no modo demonstração. Ligue <code>AG_DEMO_MODE=true</code> no back-end.</p>}
      {problem === "offline" && (
        <p className="notice" role="alert">
          Não foi possível falar com o back-end. Vou tentar de novo assim que ele voltar.
        </p>
      )}

      {report && (
        <>
          <CampaignCard
            campaign={report.campaign}
            faultCount={report.by_fault.length}
            busy={control.busy}
            error={control.actionError}
            onStart={(size) => void control.start(size)}
            onPause={() => void control.pause()}
            onResume={() => void control.resume()}
            onStop={() => void control.stop()}
          />

          {report.summary.cases === 0 ? (
            <p className="empty">Ainda não há casos. Rode uma campanha para medir a acurácia.</p>
          ) : (
            <>
              <div className="rate-grid">
                <RateCard label="Top 1" hint="Causa real em 1º lugar" rate={report.summary.top1} unit="casos" />
                <RateCard label="Top 3" hint="Causa real entre os 3 primeiros" rate={report.summary.top3} unit="casos" tone="ok" />
                <RateCard label="Alerta disparou" hint="Casos em que a falha foi detectada" rate={report.summary.detection} unit="casos" />
              </div>
              <p className="acc-note">
                Top 1 e Top 3 contam só os casos em que o alerta disparou e a análise terminou. O intervalo de confiança (IC 95%) é o de Wilson: com poucos casos ele é largo, e é ele que diz o quanto dá para confiar no número.
                {report.summary.mean_rank !== null && ` Posição média da causa real: ${report.summary.mean_rank.toFixed(1)}º.`}
              </p>

              <section className="acc-section">
                <h2>Por tipo de falha</h2>
                <FaultAccuracyList faults={report.by_fault} />
              </section>

              <CaseTable cases={report.cases} />
            </>
          )}
        </>
      )}
    </div>
  );
}
