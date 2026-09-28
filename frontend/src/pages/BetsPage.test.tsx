import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { bet, settings, summary } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";

const PAST = "2026-01-10T11:30:00Z";
const FUTURE = "2099-01-10T11:30:00Z";

function base(items = [bet({ id: 1, kickoff: PAST }), bet({ id: 2, kickoff: FUTURE })]) {
  const seen: URLSearchParams[] = [];
  server.use(
    http.get(`${API}/settings`, () => HttpResponse.json(settings)),
    http.get(`${API}/bets/summary`, ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json(summary);
    }),
    http.get(`${API}/bets`, ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json({ items, total: items.length, page: 1, size: 20 });
    }),
  );
  return seen;
}

test("panel with KPIs, monthly limit, signal progress and the ROI note", async () => {
  base();
  renderApp("/bets");
  expect(await screen.findByText("+2.10 %")).toBeInTheDocument();
  expect(screen.getByText(/ROI es mayormente ruido/)).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Uso del límite mensual" })).toHaveAttribute(
    "aria-valuenow",
    "8",
  );
  expect(screen.getByText("23/100")).toBeInTheDocument();
  expect(
    screen.getByRole("progressbar", { name: "Apuestas en papel de la señal" }),
  ).toHaveAttribute("aria-valuenow", "23");
  expect(screen.getByRole("img", { name: "Curva de bankroll" })).toBeInTheDocument();
});

test("kind filter asks the API for paper bets", async () => {
  const seen = base();
  renderApp("/bets");
  await screen.findByRole("table");
  await userEvent.click(screen.getByRole("button", { name: "En papel" }));
  await waitFor(() => expect(seen.some((p) => p.get("kind") === "paper")).toBe(true));
});

test("settle by hand only after kick-off; delete only before", async () => {
  base();
  let patch: unknown = null;
  let deleted = false;
  server.use(
    http.patch(`${API}/bets/1`, async ({ request }) => {
      patch = await request.json();
      return HttpResponse.json(bet({ id: 1, status: "ganada", result_source: "manual" }));
    }),
    http.delete(`${API}/bets/2`, () => {
      deleted = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderApp("/bets");
  const table = await screen.findByRole("table");
  const rows = within(table).getAllByRole("row");
  const started = rows[1]!;
  const upcoming = rows[2]!;
  expect(within(started).queryByRole("button", { name: /Borrar/ })).not.toBeInTheDocument();
  expect(within(upcoming).queryByLabelText(/Resultado de la apuesta/)).not.toBeInTheDocument();
  await userEvent.selectOptions(
    within(started).getByLabelText(/Resultado de la apuesta 1/),
    "ganada",
  );
  await userEvent.click(within(started).getByRole("button", { name: "Guardar" }));
  await waitFor(() => expect(patch).toEqual({ status: "ganada" }));
  await userEvent.click(within(upcoming).getByRole("button", { name: "Borrar apuesta 2" }));
  await waitFor(() => expect(deleted).toBe(true));
});

test("API refusal when settling is shown", async () => {
  base();
  server.use(
    http.patch(`${API}/bets/1`, () =>
      HttpResponse.json(
        {
          error: {
            code: "MATCH_NOT_STARTED",
            message: "el partido aún no empieza: no se puede liquidar",
            details: {},
          },
        },
        { status: 409 },
      ),
    ),
  );
  renderApp("/bets");
  const table = await screen.findByRole("table");
  const row = within(table).getAllByRole("row")[1]!;
  await userEvent.selectOptions(within(row).getByLabelText(/Resultado de la apuesta 1/), "perdida");
  await userEvent.click(within(row).getByRole("button", { name: "Guardar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("el partido aún no empieza");
});

test("bets without reference are flagged", async () => {
  base([bet({ id: 4, sin_referencia: true, kickoff: null })]);
  renderApp("/bets");
  expect(await screen.findByText("sin cuota de referencia")).toBeInTheDocument();
});

test("manual results are flagged until confirmed", async () => {
  base([bet({ id: 3, status: "ganada", result_source: "manual", profit: 17, kickoff: PAST })]);
  renderApp("/bets");
  expect(await screen.findByText("a mano, sin confirmar")).toBeInTheDocument();
});

test("settle with official results reports corrections", async () => {
  base();
  server.use(
    http.post(`${API}/bets/settle`, () =>
      HttpResponse.json({ settled: 2, clv_computed: 1, still_pending: 0, corrected: 1 }),
    ),
  );
  renderApp("/bets");
  await screen.findByRole("table");
  await userEvent.click(screen.getByRole("button", { name: "Liquidar con resultados oficiales" }));
  expect(
    await screen.findByText(/2 liquidadas · 1 con CLV · 0 pendientes · 1 corregidas/),
  ).toBeInTheDocument();
});

test("empty journal", async () => {
  base([]);
  renderApp("/bets");
  expect(await screen.findByText("No hay apuestas con estos filtros.")).toBeInTheDocument();
});
