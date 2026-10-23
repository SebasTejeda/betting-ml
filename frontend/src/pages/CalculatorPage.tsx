import { ChevronDown } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useComparator } from "../api/hooks";
import type { CalculatorResult, Outcome } from "../api/types";
import { ManualOddsForm } from "../components/ManualOddsForm";
import { NoReferenceBet } from "../components/NoReferenceBet";
import { RegisterBetForm } from "../components/RegisterBetForm";
import {
  Empty,
  ErrorBox,
  ExperimentalBadge,
  Loading,
  PageTitle,
  Panel,
} from "../components/common";
import { kickoff, todayLima } from "../lib/format";
import { readDraft } from "../lib/links";
import { cn } from "../lib/utils";

type Evaluated = { outcome: Outcome; bookmaker: string; odds: number; result: CalculatorResult };

/** Numbered step title: the page is a sequence (match → odds → register). */
function Step({ n, done = false, children }: { n: number; done?: boolean; children: ReactNode }) {
  return (
    <span className="flex items-center gap-2.5">
      <span
        aria-hidden
        className={cn(
          "num flex size-6 items-center justify-center rounded-full text-xs font-semibold",
          done ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground",
        )}
      >
        {n}
      </span>
      <span className="sr-only">Paso {n}: </span>
      {children}
    </span>
  );
}

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
      <PageTitle description="Escribe la cuota que ves en una casa peruana y compárala con la cuota justa de la referencia. Después puedes registrar la apuesta en tu diario.">
        Calculadora
      </PageTitle>
      <div className="mt-6 flex flex-col gap-5">
        <Panel
          title={
            <Step n={1} done={Boolean(matchId)}>
              Partido
            </Step>
          }
        >
          <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
            <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Fecha
              <input
                type="date"
                className="field"
                value={date}
                onChange={(event) => {
                  setDate(event.target.value || todayLima());
                  setMatchId("");
                  setEvaluated(null);
                }}
              />
            </label>
            <label className="flex min-w-0 flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Partido
              <select
                className="field"
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
          {matches.isPending && (
            <div className="mt-3">
              <Loading what="partidos" variant="table" />
            </div>
          )}
          {matches.isError && (
            <div className="mt-3">
              <ErrorBox error={matches.error} />
            </div>
          )}
          {/* The fallback lives with the match choice: it is the answer to "my match is missing". */}
          <details
            className="group mt-4 border-t pt-3"
            onToggle={(event) => setNoReferenceOpen(event.currentTarget.open)}
          >
            <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 rounded-md text-sm text-muted-foreground transition-colors hover:text-foreground">
              ¿El partido no aparece? Registrar una apuesta sin cuota de referencia
              <ChevronDown
                aria-hidden
                className="size-4 transition-transform duration-150 group-open:rotate-180"
              />
            </summary>
            <div className="mt-4">{noReferenceOpen && <NoReferenceBet defaultDate={date} />}</div>
          </details>
        </Panel>
        {!matchId ? (
          <Empty>Elige un partido para evaluar una cuota.</Empty>
        ) : fromSignal && draft?.outcome && draft.bookmaker && draft.odds ? (
          <Panel
            title={<Step n={2}>Anotar la señal experimental</Step>}
            action={<ExperimentalBadge />}
            className="border-experimental-border"
          >
            <p className="mb-4 text-sm text-muted-foreground">
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
          </Panel>
        ) : (
          <div className="grid items-start gap-5 lg:grid-cols-5">
            <Panel
              title={
                <Step n={2} done={Boolean(evaluated)}>
                  Evaluar cuota
                </Step>
              }
              className="lg:col-span-3"
            >
              <ManualOddsForm
                key={matchId}
                matchId={matchId}
                defaultOutcome={draft?.matchId === matchId ? draft.outcome : undefined}
                defaultBookmaker={draft?.matchId === matchId ? draft.bookmaker : undefined}
                defaultOdds={draft?.matchId === matchId ? draft.odds : undefined}
                onEvaluated={(input, result) => setEvaluated({ ...input, result })}
              />
            </Panel>
            <Panel title={<Step n={3}>Registrar apuesta</Step>} className="lg:col-span-2">
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
                <p className="text-sm text-muted-foreground">Evalúa primero la cuota.</p>
              )}
            </Panel>
          </div>
        )}
      </div>
    </>
  );
}
