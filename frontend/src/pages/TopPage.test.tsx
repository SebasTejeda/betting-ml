import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import type { Comparator } from "../api/types";
import { comparator, leagues } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";
import { topRows } from "../lib/top";

const base = comparator.matches[0]!;
const second = {
  ...base,
  match_id: "SP1-2026-10-10-betis-barcelona",
  league: "SP1",
  home_team: "Betis",
  away_team: "Barcelona",
  experimental_signal: {
    label: "EXPERIMENTAL — solo papel",
    bets: [
      {
        outcome: "home" as const,
        bookmaker: "coolbet",
        odds: 5.95,
        ev: 0.15,
        model_agrees: false,
        suggested_stake: 3.8,
      },
      {
        outcome: "draw" as const,
        bookmaker: "coolbet",
        odds: 3.1,
        ev: -0.01,
        model_agrees: null,
        suggested_stake: 0,
      },
    ],
  },
};
const day: Comparator = { ...comparator, count: 2, matches: [base, second] };

test("rows are every positive-EV signal price sorted by EV", () => {
  const rows = topRows(day.matches);
  expect(rows.map((r) => [r.match.home_team, r.bet.outcome, r.bet.ev])).toEqual([
    ["Betis", "home", 0.15],
    ["Arsenal", "away", 0.058],
  ]);
});

test("top of the day lists all leagues by EV with the experimental label", async () => {
  let query: URLSearchParams | null = null;
  server.use(
    http.get(`${API}/leagues`, () => HttpResponse.json(leagues)),
    http.get(`${API}/comparator`, ({ request }) => {
      query = new URL(request.url).searchParams;
      return HttpResponse.json(day);
    }),
  );
  renderApp("/top");
  const list = await screen.findByRole("list", { name: "Top del día" });
  const items = within(list).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(items[0]).toHaveTextContent("Betis – Barcelona");
  expect(items[0]).toHaveTextContent("EV +15.0 %");
  expect(items[0]).toHaveTextContent("el modelo no coincide");
  expect(items[1]).toHaveTextContent("Arsenal – Chelsea");
  expect(items[1]).toHaveTextContent("el modelo coincide");
  expect(screen.getAllByText("EXPERIMENTAL — solo papel")[0]).toBeVisible();
  expect(screen.queryByText(/recomendad/i)).not.toBeInTheDocument();
  const register = within(items[0]!).getByRole("link", { name: /Registrar en papel/ });
  expect(register).toHaveAttribute("href", expect.stringContaining("signal=1"));
  expect(register).toHaveAttribute("href", expect.stringContaining("bookmaker=coolbet"));
  await waitFor(() => expect(query?.get("only_value")).toBe("true"));
  expect(query!.get("league")).toBeNull();
});

test("empty top", async () => {
  server.use(
    http.get(`${API}/leagues`, () => HttpResponse.json(leagues)),
    http.get(`${API}/comparator`, () =>
      HttpResponse.json({ ...comparator, count: 0, matches: [] }),
    ),
  );
  renderApp("/top");
  expect(await screen.findByText("Nada con EV positivo")).toBeInTheDocument();
});
