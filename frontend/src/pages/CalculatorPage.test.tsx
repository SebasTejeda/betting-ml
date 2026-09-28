import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { MATCH_ID, bet, bookmakers, calculation, comparator } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";

function base() {
  server.use(
    http.get(`${API}/comparator`, () => HttpResponse.json(comparator)),
    http.get(`${API}/bookmakers`, () => HttpResponse.json(bookmakers)),
    http.post(`${API}/calculator`, () =>
      HttpResponse.json({ ...calculation, suggested_stake: 3.5 }),
    ),
  );
}

async function evaluate() {
  renderApp(`/calculator?match=${MATCH_ID}`);
  await screen.findByRole("option", { name: "Te Apuesto" });
  await userEvent.selectOptions(screen.getByLabelText("Resultado"), "away");
  await userEvent.selectOptions(screen.getByLabelText("Casa"), "teapuesto");
  await userEvent.type(screen.getByLabelText("Cuota"), "4.4");
  await userEvent.click(screen.getByRole("button", { name: "Evaluar" }));
  return screen.findByRole("form", { name: "Registrar apuesta" });
}

test("evaluate and register a real bet with the suggested stake", async () => {
  base();
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(bet({ id: 7 }), { status: 201 });
    }),
  );
  const form = await evaluate();
  expect(within(form).getByLabelText("Stake")).toHaveValue("3.50");
  expect(within(form).getByLabelText(/Real/)).toBeChecked();
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByText(/Apuesta real registrada \(#7\)/)).toBeInTheDocument();
  expect(bodies[0]).toMatchObject({
    match_id: MATCH_ID,
    outcome: "away",
    bookmaker: "teapuesto",
    odds: 4.4,
    stake: 3.5,
    kind: "real",
    confirm: false,
    from_experimental_signal: false,
  });
});

test("409 asks for explicit confirmation and resends with confirm: true", async () => {
  base();
  const confirms: unknown[] = [];
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      const body = (await request.json()) as { confirm: boolean };
      confirms.push(body.confirm);
      if (!body.confirm) {
        return HttpResponse.json(
          {
            error: {
              code: "LIMIT_WARNING",
              message: "El stake 25 supera el máximo por apuesta (10.00).",
              details: { messages: ["El stake 25 supera el máximo por apuesta (10.00)."] },
            },
          },
          { status: 409 },
        );
      }
      return HttpResponse.json(bet({ id: 8, warnings: ["El stake 25 supera el máximo"] }), {
        status: 201,
      });
    }),
  );
  const form = await evaluate();
  await userEvent.clear(within(form).getByLabelText("Stake"));
  await userEvent.type(within(form).getByLabelText("Stake"), "25");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Confirmación" });
  expect(dialog).toHaveTextContent("supera el máximo por apuesta");
  await userEvent.click(within(dialog).getByRole("button", { name: "Confirmar y registrar" }));
  expect(await screen.findByText(/registrada \(#8\)/)).toBeInTheDocument();
  expect(confirms).toEqual([false, true]);
});

test("409 can be cancelled without registering anything", async () => {
  base();
  let calls = 0;
  server.use(
    http.post(`${API}/bets`, () => {
      calls += 1;
      return HttpResponse.json(
        { error: { code: "LIMIT_WARNING", message: "Te acercas al límite", details: {} } },
        { status: 409 },
      );
    }),
  );
  const form = await evaluate();
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent("Te acercas al límite");
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(calls).toBe(1);
});

test("403 blocks real bets and offers paper, with no way to confirm", async () => {
  base();
  const kinds: string[] = [];
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      const body = (await request.json()) as { kind: string };
      kinds.push(body.kind);
      if (body.kind === "real") {
        return HttpResponse.json(
          {
            error: {
              code: "MONTHLY_LIMIT_REACHED",
              message: "Presupuesto mensual de pérdida superado (100.00 de 100.00).",
              details: { messages: [] },
            },
          },
          { status: 403 },
        );
      }
      return HttpResponse.json(bet({ id: 9, kind: "paper" }), { status: 201 });
    }),
  );
  const form = await evaluate();
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Apuestas reales bloqueadas este mes");
  expect(screen.queryByRole("button", { name: /Confirmar/ })).not.toBeInTheDocument();
  await userEvent.click(within(alert).getByRole("button", { name: "Cambiar a papel" }));
  expect(within(form).getByLabelText(/En papel/)).toBeChecked();
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByText(/en papel registrada \(#9\)/)).toBeInTheDocument();
  expect(kinds).toEqual(["real", "paper"]);
});

test("a bet from the experimental signal defaults to paper and is flagged", async () => {
  base();
  let body: Record<string, unknown> = {};
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(bet({ id: 10, kind: "paper" }), { status: 201 });
    }),
  );
  renderApp(`/calculator?match=${MATCH_ID}&outcome=away&bookmaker=betsson&odds=4.6&signal=1`);
  const form = await screen.findByRole("form", { name: "Registrar apuesta" });
  expect(within(form).getByText("EXPERIMENTAL — solo papel")).toBeInTheDocument();
  expect(within(form).getByLabelText(/En papel/)).toBeChecked();
  await userEvent.type(within(form).getByLabelText("Stake"), "2");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  await screen.findByText(/registrada \(#10\)/);
  expect(body).toMatchObject({
    kind: "paper",
    from_experimental_signal: true,
    bookmaker: "betsson",
    odds: 4.6,
  });
});

test("the experimental-signal 409 for real money shows the progress message", async () => {
  base();
  server.use(
    http.post(`${API}/bets`, () =>
      HttpResponse.json(
        {
          error: {
            code: "EXPERIMENTAL_SIGNAL_UNPROVEN",
            message:
              "Esta señal aún no tiene evidencia (23/100 apuestas en papel, CLV actual +1.20 %). ¿Apostar dinero real igual?",
            details: {
              messages: [
                "Esta señal aún no tiene evidencia (23/100 apuestas en papel, CLV actual +1.20 %). ¿Apostar dinero real igual?",
              ],
            },
          },
        },
        { status: 409 },
      ),
    ),
  );
  renderApp(`/calculator?match=${MATCH_ID}&outcome=away&bookmaker=betsson&odds=4.6&signal=1`);
  const form = await screen.findByRole("form", { name: "Registrar apuesta" });
  await userEvent.click(within(form).getByLabelText(/Real/));
  await userEvent.type(within(form).getByLabelText("Stake"), "2");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByRole("alertdialog")).toHaveTextContent("23/100 apuestas en papel");
});

test("stake validation", async () => {
  base();
  const form = await evaluate();
  await userEvent.clear(within(form).getByLabelText("Stake"));
  await userEvent.type(within(form).getByLabelText("Stake"), "1.234");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByText(/máximo 2 decimales/)).toBeInTheDocument();
});

test("a 'valor' verdict is the experimental signal: paper by default and flagged", async () => {
  server.use(
    http.get(`${API}/comparator`, () => HttpResponse.json(comparator)),
    http.get(`${API}/bookmakers`, () => HttpResponse.json(bookmakers)),
    http.post(`${API}/calculator`, () =>
      HttpResponse.json({ ...calculation, verdict: "valor", ev: 0.05, suggested_stake: 2.5 }),
    ),
  );
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      bodies.push(body);
      return HttpResponse.json(
        {
          error: {
            code: "EXPERIMENTAL_SIGNAL_UNPROVEN",
            message:
              "Esta señal aún no tiene evidencia (0/100 apuestas en papel, CLV actual sin datos). ¿Apostar dinero real igual?",
            details: {},
          },
        },
        { status: 409 },
      );
    }),
  );
  const form = await evaluate();
  expect(within(form).getByLabelText(/En papel/)).toBeChecked();
  expect(within(form).getByText("EXPERIMENTAL — solo papel")).toBeInTheDocument();
  await userEvent.click(within(form).getByLabelText(/Real/));
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByRole("alertdialog")).toHaveTextContent("0/100 apuestas en papel");
  expect(bodies[0]).toMatchObject({ kind: "real", from_experimental_signal: true, confirm: false });
});

test("a bet on a match without odds is registered with the no-reference notice", async () => {
  base();
  server.use(
    http.get(`${API}/leagues`, () =>
      HttpResponse.json([{ code: "SP1", name: "LaLiga", country: "Spain", teams: 20 }]),
    ),
    http.get(`${API}/leagues/SP1/teams`, () =>
      HttpResponse.json([
        { name: "Alaves", elo: 1500 },
        { name: "Ath Madrid", elo: 1700 },
      ]),
    ),
  );
  let body: Record<string, unknown> = {};
  server.use(
    http.post(`${API}/bets`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(
        bet({
          id: 11,
          sin_referencia: true,
          warnings: ["Sin cuota de referencia: el partido no tiene cuotas de la API."],
        }),
        { status: 201 },
      );
    }),
  );
  renderApp("/calculator");
  // jsdom does not toggle <details> on click: open it and fire the event the page listens to
  const details = (await screen.findByText(/El partido no aparece/)).closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  await screen.findByRole("option", { name: "LaLiga" });
  await userEvent.selectOptions(screen.getAllByLabelText("Liga")[0]!, "SP1");
  await within(screen.getByLabelText("Local")).findByRole("option", { name: "Ath Madrid" });
  fireEvent.change(screen.getByLabelText("Fecha del partido"), { target: { value: "2026-10-10" } });
  await userEvent.selectOptions(screen.getByLabelText("Local"), "Alaves");
  await userEvent.selectOptions(screen.getByLabelText("Visita"), "Ath Madrid");
  await userEvent.selectOptions(screen.getAllByLabelText("Resultado")[0]!, "away");
  await userEvent.selectOptions(screen.getAllByLabelText("Casa")[0]!, "teapuesto");
  await userEvent.type(screen.getAllByLabelText("Cuota")[0]!, "2.1");
  const form = await screen.findByRole("form", { name: "Registrar apuesta" });
  expect(within(form).getByRole("note")).toHaveTextContent("Sin cuota de referencia");
  expect(within(form).getByLabelText(/Real/)).toBeChecked();
  await userEvent.type(within(form).getByLabelText("Stake"), "5");
  await userEvent.click(within(form).getByRole("button", { name: "Registrar apuesta" }));
  expect(await screen.findByText(/registrada \(#11\)/)).toBeInTheDocument();
  expect(screen.getByText(/Sin cuota de referencia: el partido/)).toBeInTheDocument();
  expect(body).toMatchObject({
    match_id: "SP1-2026-10-10-alaves-ath-madrid",
    outcome: "away",
    bookmaker: "teapuesto",
    odds: 2.1,
    kind: "real",
    from_experimental_signal: false,
  });
}, 20_000);
