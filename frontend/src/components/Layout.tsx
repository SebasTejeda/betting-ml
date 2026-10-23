import {
  Activity,
  Calculator,
  CalendarDays,
  ChartLine,
  ListOrdered,
  Settings,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import { Suspense } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

import { Loading } from "./common";
import { LogoutButton } from "./LogoutButton";
import { ThemeToggle } from "./ThemeToggle";

const LINKS = [
  { to: "/", label: "Hoy", icon: CalendarDays, end: true },
  { to: "/top", label: "Top del día", short: "Top", icon: ListOrdered },
  { to: "/analysis", label: "Análisis", icon: Sparkles },
  { to: "/calculator", label: "Calculadora", short: "Calcular", icon: Calculator },
  { to: "/bets", label: "Mis apuestas", short: "Apuestas", icon: Wallet },
  { to: "/backtest", label: "Backtest", icon: ChartLine },
  { to: "/settings", label: "Ajustes", icon: Settings },
];

export function Layout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Activity aria-hidden className="size-4" />
            </span>
            <span>betting-ml</span>
            <span className="sr-only">Comparador de cuotas</span>
          </Link>
          <nav aria-label="Principal" className="hidden flex-1 items-center gap-1 md:flex">
            {LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors duration-150",
                    isActive
                      ? "bg-secondary font-medium text-foreground"
                      : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                  )
                }
              >
                <link.icon aria-hidden className="size-4" />
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <LogoutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 pt-6 pb-8">
        <Suspense fallback={<Loading what="la página" />}>
          <Outlet />
        </Suspense>
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-24 md:pb-8">
        <p className="flex items-start gap-2 rounded-lg border bg-card p-3 text-xs text-muted-foreground">
          <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
          <span>
            Juego responsable: apuesta solo lo que puedas perder. Los límites mensuales no se pueden
            saltar desde esta app. Si sientes que pierdes el control, busca ayuda.
          </span>
        </p>
      </footer>
      <nav
        aria-label="Principal (móvil)"
        className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        <ul className="grid grid-cols-6">
          {LINKS.map((link) => (
            <li key={link.to}>
              <NavLink
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  cn(
                    "flex flex-col items-center gap-0.5 px-1 py-2 text-[0.68rem] transition-colors duration-150",
                    isActive ? "text-primary" : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                <link.icon aria-hidden className="size-5" />
                <span className="truncate">{link.short ?? link.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
