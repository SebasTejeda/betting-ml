import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { getApiKey } from "./lib/apiKey";
import { renderApp } from "./test/render";

test("renders the navigation and the responsible gambling notice", () => {
  renderApp("/backtest");
  const nav = screen.getByRole("navigation", { name: "Principal" });
  for (const label of ["Hoy", "Calculadora", "Mis apuestas", "Backtest", "Ajustes"]) {
    expect(nav).toHaveTextContent(label);
  }
  expect(screen.getByText(/Juego responsable/)).toBeInTheDocument();
});

test("unknown routes show a not found message", () => {
  renderApp("/nope");
  expect(screen.getByText("Página no encontrada.")).toBeInTheDocument();
});

test("the write key is stored in this browser", async () => {
  renderApp("/nope");
  await userEvent.click(screen.getByRole("button", { name: "Configurar clave" }));
  await userEvent.type(screen.getByLabelText(/Clave de escritura/), "secret-key");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  expect(getApiKey()).toBe("secret-key");
  expect(screen.getByRole("button", { name: "Clave configurada ✓" })).toBeInTheDocument();
});
