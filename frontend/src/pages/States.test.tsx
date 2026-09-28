import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { MATCH_ID, detail, settings } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";

const boom = () =>
  HttpResponse.json(
    { error: { code: "INTERNAL_ERROR", message: "Algo falló en el servidor", details: {} } },
    { status: 500 },
  );

test.each([
  ["/match/" + MATCH_ID, `${API}/comparator/${MATCH_ID}`],
  ["/backtest", `${API}/backtest/pinnacle`],
  ["/settings", `${API}/settings`],
])("%s shows server errors", async (path, url) => {
  server.use(
    http.get(url, boom),
    http.get(`${API}/bookmakers`, () => HttpResponse.json([])),
  );
  renderApp(path);
  expect(await screen.findByRole("alert")).toHaveTextContent("Algo falló en el servidor");
});

test("journal shows a summary error without hiding the table", async () => {
  server.use(
    http.get(`${API}/settings`, () => HttpResponse.json(settings)),
    http.get(`${API}/bets/summary`, boom),
    http.get(`${API}/bets`, () => HttpResponse.json({ items: [], total: 0, page: 1, size: 20 })),
  );
  renderApp("/bets");
  expect(await screen.findByRole("alert")).toHaveTextContent("Algo falló en el servidor");
  expect(await screen.findByText("No hay apuestas con estos filtros.")).toBeInTheDocument();
});

test("match without bookmakers nor reference history", async () => {
  server.use(
    http.get(`${API}/comparator/${MATCH_ID}`, () =>
      HttpResponse.json({
        ...detail,
        bookmakers: [],
        reference_history: [],
        experimental_signal: null,
        fair: null,
        warning: "Sin cuota de referencia",
      }),
    ),
    http.get(`${API}/bookmakers`, () => HttpResponse.json([])),
  );
  renderApp(`/match/${MATCH_ID}`);
  expect(await screen.findByText("Sin cuotas de casas para este partido.")).toBeInTheDocument();
  expect(screen.getByText(/Aún no hay suficientes snapshots/)).toBeInTheDocument();
  expect(screen.getByText("Sin cuota de referencia")).toBeInTheDocument();
  expect(screen.queryByText("EXPERIMENTAL — solo papel")).not.toBeInTheDocument();
});

test("calculator without a match asks to choose one", async () => {
  server.use(
    http.get(`${API}/comparator`, () =>
      HttpResponse.json({
        date: "2026-10-10",
        snapshot_at: null,
        reference: "pinnacle",
        count: 0,
        matches: [],
      }),
    ),
  );
  renderApp("/calculator");
  expect(await screen.findByText("Elige un partido para evaluar una cuota.")).toBeInTheDocument();
});
