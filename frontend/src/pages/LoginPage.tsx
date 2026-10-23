import { LogIn, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/context";
import { ErrorBox } from "../components/common";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";

function loginError(error: unknown): Error {
  if (error instanceof ApiError && error.status === 429) {
    return new Error(
      error.retryAfter
        ? `Demasiados intentos. Vuelve a intentarlo en ${error.retryAfter} s.`
        : "Demasiados intentos. Espera un momento antes de reintentar.",
    );
  }
  return error instanceof Error ? error : new Error("Error inesperado");
}

export function LoginPage() {
  const { status, expired, login } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [blockedFor, setBlockedFor] = useState(0);

  // after a 429 the button stays disabled for the Retry-After seconds
  useEffect(() => {
    if (blockedFor <= 0) return;
    const timer = setTimeout(() => setBlockedFor(0), blockedFor * 1000);
    return () => clearTimeout(timer);
  }, [blockedFor]);

  if (status === "authenticated" && !pending) return <Navigate to={from} replace />;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <div className="flex justify-end p-3">
        <ThemeToggle />
      </div>
      <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-4 pb-24">
        {/* Same mark as the app header, so the login reads as the same product. */}
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span
            aria-hidden
            className="num flex size-10 items-center justify-center rounded-lg bg-foreground text-base font-bold text-background"
          >
            b
          </span>
          <div>
            <p className="text-lg font-semibold tracking-tight">
              betting<span className="text-muted-foreground">-ml</span>
            </p>
            <p className="text-sm text-muted-foreground">Comparador de cuotas</p>
          </div>
        </div>
        <Card className="gap-5 p-6">
          <h1 className="text-lg font-semibold tracking-tight">Iniciar sesión</h1>
          <form
            className="flex flex-col gap-4"
            noValidate
            aria-label="Iniciar sesión"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!password) return;
              setPending(true);
              setError(null);
              try {
                await login(password);
                navigate(from, { replace: true });
              } catch (failure) {
                setError(loginError(failure));
                if (failure instanceof ApiError && failure.status === 429) {
                  setBlockedFor(failure.retryAfter ?? 60);
                }
              } finally {
                setPassword("");
                setPending(false);
              }
            }}
          >
            {expired && (
              <p role="status" className="text-sm text-muted-foreground">
                Tu sesión expiró. Vuelve a entrar.
              </p>
            )}
            <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Contraseña
              <input
                className="field"
                type="password"
                name="password"
                autoComplete="current-password"
                maxLength={1024}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error && <ErrorBox error={error} />}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={pending || blockedFor > 0 || !password}
            >
              <LogIn aria-hidden />
              Entrar
            </Button>
          </form>
        </Card>
        <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck aria-hidden className="size-3.5" />
          Acceso privado. Tras varios intentos fallidos se bloquea un momento.
        </p>
      </main>
    </div>
  );
}
