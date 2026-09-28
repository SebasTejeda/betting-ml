import { useState } from "react";

import { useBookmakers, useLeagues, useTeams } from "../api/hooks";
import { OUTCOME_LABEL, OUTCOMES, type Outcome } from "../api/types";
import { makeMatchId } from "../lib/matchId";
import { RegisterBetForm } from "./RegisterBetForm";

/** Registers a bet on a match without API odds (no reference price). The journal must hold
 *  every real bet so that the limits and the CLV are reliable (decisions.md). */
export function NoReferenceBet({ defaultDate }: { defaultDate: string }) {
  const leagues = useLeagues();
  const bookmakers = useBookmakers();
  const [league, setLeague] = useState("");
  const [date, setDate] = useState(defaultDate);
  const [home, setHome] = useState("");
  const [away, setAway] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("home");
  const [bookmaker, setBookmaker] = useState("");
  const [odds, setOdds] = useState("");
  const teams = useTeams(league);
  const price = Number(odds.replace(",", "."));
  const ready =
    league &&
    date &&
    home &&
    away &&
    home !== away &&
    bookmaker &&
    Number.isFinite(price) &&
    price > 1;
  const accessible = (bookmakers.data ?? []).filter((b) => b.accessible);
  const select = "rounded border border-slate-300 px-2 py-1";

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col text-sm">
          Liga
          <select
            className={select}
            value={league}
            onChange={(e) => {
              setLeague(e.target.value);
              setHome("");
              setAway("");
            }}
          >
            <option value="">Elige…</option>
            {leagues.data?.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Fecha del partido
          <input
            type="date"
            className={select}
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className="flex flex-col text-sm">
          Local
          <select className={select} value={home} onChange={(e) => setHome(e.target.value)}>
            <option value="">Elige…</option>
            {teams.data?.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Visita
          <select className={select} value={away} onChange={(e) => setAway(e.target.value)}>
            <option value="">Elige…</option>
            {teams.data?.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Resultado
          <select
            className={select}
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as Outcome)}
          >
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {OUTCOME_LABEL[o]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Casa
          <select
            className={select}
            value={bookmaker}
            onChange={(e) => setBookmaker(e.target.value)}
          >
            <option value="">Elige…</option>
            {accessible.map((b) => (
              <option key={b.key} value={b.key}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Cuota
          <input
            inputMode="decimal"
            className={select}
            value={odds}
            onChange={(e) => setOdds(e.target.value)}
          />
        </label>
      </div>
      {home && away && home === away && (
        <p className="text-xs text-red-700">Local y visita deben ser distintos.</p>
      )}
      {ready ? (
        <RegisterBetForm
          key={`${league}-${date}-${home}-${away}-${outcome}-${bookmaker}-${price}`}
          matchId={makeMatchId(league, date, home, away)}
          outcome={outcome}
          bookmaker={bookmaker}
          odds={price}
          noReference
        />
      ) : (
        <p className="text-sm text-slate-600">
          Completa el partido, la casa y la cuota para registrar la apuesta.
        </p>
      )}
    </div>
  );
}
