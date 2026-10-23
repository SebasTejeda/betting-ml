import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { api, unwrap } from "@/api/client";
import { forgetLegacySecrets, onUnauthorized, setCsrfToken } from "@/lib/session";

import { AuthContext, type AuthState, type AuthStatus } from "./context";

/** Owner session (spec 003, US1): asks /auth/me on load and drops every cached datum on logout
 * or on any 401, so personal data does not outlive the session in memory. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [expired, setExpired] = useState(false);

  const end = useCallback(
    (byServer: boolean) => {
      setCsrfToken(null);
      queryClient.clear();
      setExpired(byServer);
      setStatus("anonymous");
    },
    [queryClient],
  );

  useEffect(() => {
    forgetLegacySecrets();
    let active = true;
    const unsubscribe = onUnauthorized(() => {
      if (active) end(true);
    });
    unwrap(api.GET("/api/v1/auth/me"))
      .then((me) => {
        if (!active) return;
        setCsrfToken(me.csrf_token);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        setCsrfToken(null);
        setStatus("anonymous");
        setExpired(false); // no session on load is not an expiry
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [end]);

  const login = useCallback(
    async (password: string) => {
      const session = await unwrap(api.POST("/api/v1/auth/login", { body: { password } }));
      queryClient.clear();
      setCsrfToken(session.csrf_token);
      setExpired(false);
      setStatus("authenticated");
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await unwrap(api.POST("/api/v1/auth/logout"));
    } finally {
      end(false);
    }
  }, [end]);

  const value = useMemo<AuthState>(
    () => ({ status, expired, login, logout }),
    [status, expired, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
