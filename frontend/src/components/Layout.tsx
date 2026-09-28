import { NavLink, Outlet } from "react-router-dom";

import { ApiKeyButton } from "./ApiKeyButton";

const LINKS = [
  { to: "/", label: "Hoy", end: true },
  { to: "/calculator", label: "Calculadora" },
  { to: "/bets", label: "Mis apuestas" },
  { to: "/backtest", label: "Backtest" },
  { to: "/settings", label: "Ajustes" },
];

export function Layout() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="font-semibold text-slate-900">Comparador de cuotas</span>
          <nav aria-label="Principal" className="flex flex-wrap gap-1">
            {LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  `rounded px-3 py-1.5 text-sm ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <ApiKeyButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-slate-600">
        Juego responsable: apuesta solo lo que puedas perder. Los límites mensuales no se pueden
        saltar desde esta app. Si sientes que pierdes el control, busca ayuda.
      </footer>
    </div>
  );
}
