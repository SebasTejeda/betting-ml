import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { analysis, bet, MOST_LIKELY } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";

const PAGE = "/analysis?home=Real%20Madrid&away=Barcelona&date=2026-10-26";

function base(body = analysis()) {
  server.use(
    http.get(`${API}/analysis`, () => HttpResponse.json(body)),
    http.get(`${API}/teams/search`, () => HttpResponse.json([])),
    http.get(`${API}/analysis/:matchId/odds/estimate`, () =>
      HttpResponse.json({ markets: 6, regions: 2, estimated_credits: 12, credits_remaining: 480 }),
    ),
  );
}

function apiError(status: number, code: string, message: string, details = {}) {
  return HttpResponse.json({ error: { code, message, details } }, { status });
}

test("full analysis: scoreboard, disabled best options, honest most likely, form and markets", async () => {
  base();
  renderApp(PAGE);
  expect(
    await screen.findByRole("heading", { name: "Real Madrid – Barcelona" }),
  ).toBeInTheDocument();
  expect(screen.getByText("2.09")).toBeInTheDocument();
  expect(
    await screen.findByText(/Actualizar cuesta unos 12 créditos \(quedan 480\)/),
  ).toBeInTheDocument();
  expect(screen.getByText("Los consejos de valor están desactivados.")).toBeInTheDocument();
  const card = screen.getByRole("article");
  expect(within(card).getByText("Ambos marcan: sí")).toBeInTheDocument();
  expect(within(card).getByText(MOST_LIKELY.price_comment)).toBeInTheDocument();
  expect(within(card).getByLabelText("A favor")).toBeInTheDocument();
  expect(within(card).getByLabelText("En contra")).toBeInTheDocument();
  expect(within(card).getByRole("meter", { name: "Probabilidad del modelo" })).toHaveAttribute(
    "aria-valuenow",
    "75",
  );
  // Recent form: W/L chips with an accessible description (both teams).
  expect(screen.getAllByText(/Victoria ante Sevilla 4-1/)).toHaveLength(2);
  // Markets: "baja" rows are information only.
  expect(screen.getAllByText("Solo información").length).toBeGreaterThan(0);
  expect(screen.getByText("sin cuota")).toBeInTheDocument();
  // No certainty language anywhere (principle XII).
  expect(document.body.textContent?.toLowerCase()).not.toMatch(
    / segura| fija |garantizad|no falla/,
  );
});

test("registering from a most likely card sends market/selection and defaults to paper", async () => {
  base();
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(
        bet({ id: 9, kind: "paper", market: "btts", outcome: null, selection: "yes" }),
        { status: 201 },
      );
    }),
  );
  renderApp(PAGE);
  const card = await screen.findByRole("article");
  await userEvent.click(within(card).getByRole("button", { name: "Registrar en papel" }));
  const form = within(card).getByRole("form", { name: "Registrar apuesta" });
  expect(within(form).getByLabelText("En papel")).toBeChecked();
  await userEvent.type(within(form).getByLabelText("Stake"), "5");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByText(/Apuesta en papel registrada \(#9\)/)).toBeInTheDocument();
  expect(bodies[0]).toMatchObject({
    match_id: "SP1-2026-10-26-real-madrid-barcelona",
    outcome: null,
    market: "btts",
    selection: "yes",
    line: null,
    bookmaker: "betsson",
    odds: 1.28,
    kind: "paper",
    from_experimental_signal: false,
    confirm: false,
  });
});

test("a selection without odds asks for the price; a 409 asks for confirmation", async () => {
  base();
  const confirms: unknown[] = [];
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      const body = (await request.json()) as { confirm: boolean };
      confirms.push(body.confirm);
      if (!body.confirm) {
        return apiError(409, "LIMIT_WARNING", "Stake alto", {
          messages: ["Stake por encima del máximo"],
        });
      }
      return HttpResponse.json(
        bet({ id: 10, market: "totals", outcome: null, selection: "over", line: 4.5 }),
        { status: 201 },
      );
    }),
  );
  renderApp(PAGE);
  const row = (await screen.findByText("Más de 4.5 goles")).closest("tr") as HTMLElement;
  await userEvent.click(within(row).getByRole("button", { name: "Registrar" }));
  const form = screen.getByRole("form", { name: "Registrar apuesta" });
  await userEvent.type(within(form).getByLabelText("Stake"), "50");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await within(form).findByText("Cuota inválida (mayor que 1)")).toBeInTheDocument();
  await userEvent.type(within(form).getByLabelText(/Cuota que te ofrecen/), "2.9");
  await userEvent.type(within(form).getByLabelText(/^Casa/), "teapuesto");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Confirmación" });
  expect(within(dialog).getByText("Stake por encima del máximo")).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Confirmar y registrar" }));
  expect(await screen.findByText(/registrada \(#10\)/)).toBeInTheDocument();
  expect(confirms).toEqual([false, true]);
});

test("no value: most likely empty and an explicit message", async () => {
  base(
    analysis({
      most_likely: [],
      best_options_note: null,
      no_value_message:
        "Hoy no hay apuestas con valor en este partido. No apostar también es una decisión.",
    }),
  );
  renderApp(PAGE);
  expect(
    await screen.findByText(/Ninguna selección tiene confianza suficiente/),
  ).toBeInTheDocument();
  expect(screen.getByText(/No apostar también es una decisión/)).toBeInTheDocument();
});

test("cross-league match shows its badge, ratings and warnings", async () => {
  const sample = analysis();
  base(
    analysis({
      match: {
        ...sample.match,
        match_id: "UCL-2026-10-28-real-madrid-rb-leipzig",
        competition: "UCL",
        away_team: "RB Leipzig",
        cross_league: true,
        model: "cross_league_elo",
        ratings: { home: 1800, away: 1700, source: "elo_propio", date: "2026-10-26" },
        warnings: ["Partido entre ligas: la fuerza se ajusta con el Elo entre ligas."],
      },
      most_likely: [],
    }),
  );
  renderApp(
    "/analysis?home=Real%20Madrid&away=RB%20Leipzig&match=UCL-2026-10-28-real-madrid-rb-leipzig",
  );
  expect(await screen.findByText("Entre ligas")).toBeInTheDocument();
  expect(screen.getByText("Elo 1800")).toBeInTheDocument();
  expect(screen.getByText(/Partido entre ligas: la fuerza se ajusta/)).toBeInTheDocument();
});

test("no odds: the refresh button reports the API error", async () => {
  base();
  server.use(
    http.post(`${API}/analysis/:matchId/odds/refresh`, () =>
      apiError(503, "ODDS_API_NOT_CONFIGURED", "ODDS_API_KEY is not configured"),
    ),
  );
  renderApp(PAGE);
  expect(await screen.findByText(/Sin cuotas por evento/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Actualizar cuotas de este partido" }));
  expect(await screen.findByText(/ODDS_API_KEY is not configured/)).toBeInTheDocument();
});

test("refreshing from the cache spends nothing", async () => {
  base();
  server.use(
    http.post(`${API}/analysis/:matchId/odds/refresh`, () =>
      HttpResponse.json({
        match_id: "SP1-2026-10-26-real-madrid-barcelona",
        markets: ["h2h"],
        credits_used: 0,
        credits_remaining: 480,
        fetched_at: "2026-10-22T10:00:00+00:00",
        from_cache: true,
      }),
    ),
  );
  renderApp(PAGE);
  await userEvent.click(
    await screen.findByRole("button", { name: "Actualizar cuotas de este partido" }),
  );
  expect(await screen.findByText(/no se gastaron créditos/)).toBeInTheDocument();
});

test("team errors", async () => {
  server.use(
    http.get(`${API}/teams/search`, () => HttpResponse.json([])),
    http.get(`${API}/analysis`, ({ request }) => {
      const away = new URL(request.url).searchParams.get("away");
      return away === "Lonely FC"
        ? apiError(503, "RATINGS_UNAVAILABLE", "x")
        : apiError(404, "TEAM_NOT_FOUND", "team not found: Nadie");
    }),
  );
  renderApp("/analysis?home=Nadie&away=Barcelona&date=2026-10-26");
  expect(await screen.findByText("Equipo no encontrado")).toBeInTheDocument();
});

test("ratings unavailable for a cross-league match", async () => {
  server.use(
    http.get(`${API}/teams/search`, () => HttpResponse.json([])),
    http.get(`${API}/analysis`, () => apiError(503, "RATINGS_UNAVAILABLE", "x")),
  );
  renderApp("/analysis?home=Real%20Madrid&away=Lonely%20FC&date=2026-10-28");
  expect(await screen.findByText("Sin rating para este partido")).toBeInTheDocument();
});

test("search: autocomplete, fixture lookup and an empty start", async () => {
  const requests: string[] = [];
  server.use(
    http.get(`${API}/teams/search`, () =>
      HttpResponse.json([
        { name: "Real Madrid", league: "SP1", rating: 1800, rating_source: "elo_propio" },
      ]),
    ),
    http.get(`${API}/analysis/fixture`, () =>
      HttpResponse.json({
        found: true,
        match_id: "SP1-2026-10-26-real-madrid-barcelona",
        competition: "SP1",
        kickoff: null,
        date: "2026-10-26",
      }),
    ),
    http.get(`${API}/analysis`, ({ request }) => {
      requests.push(new URL(request.url).search);
      return HttpResponse.json(analysis());
    }),
    http.get(`${API}/analysis/:matchId/odds/estimate`, () =>
      HttpResponse.json({
        markets: 6,
        regions: 2,
        estimated_credits: 12,
        credits_remaining: null,
      }),
    ),
  );
  renderApp("/analysis");
  expect(await screen.findByText("Elige un partido")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Local"), "Real Madrid");
  await userEvent.type(screen.getByLabelText("Visita"), "Barcelona");
  await userEvent.click(screen.getByRole("button", { name: "Analizar" }));
  expect(
    await screen.findByRole("heading", { name: "Real Madrid – Barcelona" }),
  ).toBeInTheDocument();
  expect(requests[0]).toContain("match_id=SP1-2026-10-26-real-madrid-barcelona");
});
