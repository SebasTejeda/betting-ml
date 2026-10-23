import {
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

// Daily tasks first; the evidence and the settings after a divider (spec 005).
const PRIMARY = [
  { to: "/", label: "Hoy", icon: CalendarDays, end: true },
  { to: "/top", label: "Top del día", short: "Top", icon: ListOrdered },
  { to: "/analysis", label: "Análisis", icon: Sparkles },
  { to: "/calculator", label: "Calculadora", short: "Calcular", icon: Calculator },
  { to: "/bets", label: "Mis apuestas", short: "Apuestas", icon: Wallet },
];
const SECONDARY = [
  { to: "/backtest", label: "Backtest", icon: ChartLine },
  { to: "/settings", label: "Ajustes", icon: Settings },
];

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-md">
      <span
        aria-hidden
        className="num flex size-7 items-center justify-center rounded-md bg-foreground text-[0.7rem] font-bold tracking-tight text-background"
      >
        b
      </span>
      <span className="text-[0.95rem] font-semibold tracking-tight">
        betting<span className="text-muted-foreground">-ml</span>
      </span>
      <span className="sr-only">Comparador de cuotas</span>
    </Link>
  );
}

const desktopLink = ({ isActive }: { isActive: boolean }) =>
  cn(
    "relative flex h-16 items-center px-3 text-sm transition-colors duration-150",
    "after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:transition-colors",
    isActive
      ? "font-medium text-foreground after:bg-primary"
      : "text-muted-foreground after:bg-transparent hover:text-foreground",
  );

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      {/* Keyboard users skip the seven navigation links on every page (WCAG 2.4.1). */}
      <a
        href="#contenido"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Saltar al contenido
      </a>
      <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <Brand />
          <nav aria-label="Principal" className="hidden flex-1 items-center lg:flex">
            {PRIMARY.map((link) => (
              <NavLink key={link.to} to={link.to} end={link.end} className={desktopLink}>
                {link.label}
              </NavLink>
            ))}
            <span aria-hidden className="mx-2 h-5 w-px bg-border" />
            {SECONDARY.map((link) => (
              <NavLink key={link.to} to={link.to} className={desktopLink}>
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            {/* Below lg the bottom bar holds the daily tasks; these two live up here. */}
            <nav aria-label="Secundaria" className="flex items-center gap-1 lg:hidden">
              {SECONDARY.map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  aria-label={link.label}
                  className={({ isActive }) =>
                    cn(
                      "flex size-10 items-center justify-center rounded-md transition-colors",
                      // Active is a filled tile, not only a colour change.
                      isActive
                        ? "bg-secondary text-primary"
                        : "text-muted-foreground hover:text-foreground",
                    )
                  }
                >
                  <link.icon aria-hidden className="size-[1.125rem]" />
                </NavLink>
              ))}
            </nav>
            <ThemeToggle />
            <LogoutButton />
          </div>
        </div>
      </header>
      <main
        id="contenido"
        tabIndex={-1}
        className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-10 outline-none sm:px-6"
      >
        <Suspense fallback={<Loading what="la página" />}>
          <Outlet />
        </Suspense>
      </main>
      <footer className="border-t">
        <p className="mx-auto flex max-w-6xl items-start gap-2 px-4 pt-4 pb-24 text-xs text-muted-foreground sm:px-6 lg:pb-6">
          <ShieldCheck aria-hidden className="mt-px size-4 shrink-0" />
          <span>
            Juego responsable: apuesta solo lo que puedas perder. Los límites mensuales no se pueden
            saltar desde esta app. Si sientes que pierdes el control, busca ayuda.
          </span>
        </p>
      </footer>
      <nav
        aria-label="Principal (móvil)"
        className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        <ul className="grid grid-cols-5">
          {PRIMARY.map((link) => (
            <li key={link.to}>
              <NavLink
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  cn(
                    "flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[0.68rem] transition-colors duration-150",
                    isActive ? "font-medium text-primary" : "text-muted-foreground",
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
