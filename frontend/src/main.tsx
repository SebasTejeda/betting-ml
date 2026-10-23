import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { z } from "zod";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import "./index.css";
import { makeQueryClient } from "./lib/queryClient";

// Zod compiles validators with `new Function` unless told not to; the CSP forbids eval.
z.config({ jitless: true });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={makeQueryClient()}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
