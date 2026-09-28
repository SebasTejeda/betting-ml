import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useComparator } from "../api/hooks";
import type { CalculatorResult, Outcome } from "../api/types";
import { ManualOddsForm } from "../components/ManualOddsForm";
import { NoReferenceBet } from "../components/NoReferenceBet";
import { RegisterBetForm } from "../components/RegisterBetForm";
import { Card, Empty, ErrorBox, Loading, PageTitle } from "../components/ui";
import { kickoff, todayLima } from "../lib/format";
import { readDraft } from "../lib/links";

type Evaluated = { outcome: Outcome; bookmaker: string; odds: number; result: CalculatorResult };

export function CalculatorPage() {
  const [params] = useSearchParams();
  const draft = readDraft(params);
  const [date, setDate] = useState(
    () => draft?.matchId.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? todayLima(),
  );
  const [matchId, setMatchId] = useState(draft?.matchId ?? "");
  const [evaluated, setEvaluated] = useState<Evaluated | null>(null);
  const [noReferenceOpen, setNoReferenceOpen] = useState(false);
  const matches = useComparator({ date, accessibleOnly: true });
  const fromSignal = Boolean(
    draft?.fromSignal &&
    draft.matchId === matchId &&
    draft.outcome &&
    draft.bookmaker &&
    draft.odds,
  );

  return (
    <>
      <PageTitle>Calculadora</PageTitle>
      <p className="mb-4 text-sm text-slate-600">
        Escribe la cuota que ves en una casa peruana y compárala con la cuota justa de la
        referencia. Después puedes registrar la apuesta en tu diario.
      </p>
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col text-sm">
            Fecha
            <input
              type="date"
              className="rounded border border-slate-300 px-2 py-1"
              value={date}
              onChange={(event) => {
                setDate(event.target.value || todayLima());
                setMatchId("");
                setEvaluated(null);
              }}
            />
          </label>
          <label className="flex min-w-64 flex-1 flex-col text-sm">
            Partido
            <select
              className="rounded border border-slate-300 px-2 py-1"
              value={matchId}
              onChange={(event) => {
                setMatchId(event.target.value);
                setEvaluated(null);
              }}
            >
              <option value="">Elige un partido…</option>
              {matches.data?.matches.map((m) => (
                <option key={m.match_id} value={m.match_id}>
                  {m.home_team} – {m.away_team} ({m.league}, {kickoff(m.kickoff)})
                </option>
              ))}
              {matchId && !matches.data?.matches.some((m) => m.match_id === matchId) && (
                <option value={matchId}>{matchId}</option>
              )}
            </select>
          </label>
        </div>
        {matches.isPending && <Loading what="partidos" />}
        {matches.isError && <ErrorBox error={matches.error} />}
      </Card>
      <details
        className="mb-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        onToggle={(event) => setNoReferenceOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer text-sm font-medium">
          ¿El partido no aparece? Registrar una apuesta sin cuota de referencia
        </summary>
        <div className="mt-3">{noReferenceOpen && <NoReferenceBet defaultDate={date} />}</div>
      </details>
      {!matchId ? (
        <Empty>Elige un partido para evaluar una cuota.</Empty>
      ) : fromSignal && draft?.outcome && draft.bookmaker && draft.odds ? (
        <Card>
          <h2 className="mb-2 font-semibold">Anotar la señal experimental</h2>
          <p className="mb-3 text-sm text-slate-600">
            La señal todavía no tiene evidencia: por defecto se registra en papel. Hacen falta 100
            apuestas en papel con CLV positivo para considerarla.
          </p>
          <RegisterBetForm
            key={`${matchId}-signal`}
            matchId={matchId}
            outcome={draft.outcome}
            bookmaker={draft.bookmaker}
            odds={draft.odds}
            fromSignal
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <h2 className="mb-2 font-semibold">Evaluar cuota</h2>
            <ManualOddsForm
              key={matchId}
              matchId={matchId}
              defaultOutcome={draft?.matchId === matchId ? draft.outcome : undefined}
              defaultBookmaker={draft?.matchId === matchId ? draft.bookmaker : undefined}
              defaultOdds={draft?.matchId === matchId ? draft.odds : undefined}
              onEvaluated={(input, result) => setEvaluated({ ...input, result })}
            />
          </Card>
          <Card>
            <h2 className="mb-2 font-semibold">Registrar apuesta</h2>
            {evaluated ? (
              <RegisterBetForm
                key={`${evaluated.bookmaker}-${evaluated.outcome}-${evaluated.odds}`}
                matchId={matchId}
                outcome={evaluated.outcome}
                bookmaker={evaluated.bookmaker}
                odds={evaluated.odds}
                suggestedStake={evaluated.result.suggested_stake}
                // a "valor" verdict IS the experimental signal: paper by default, flagged
                fromSignal={evaluated.result.verdict === "valor"}
              />
            ) : (
              <p className="text-sm text-slate-600">Evalúa primero la cuota.</p>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
