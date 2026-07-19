import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/jetbrains-mono/400.css";
import "./styles/tokens.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { SessionProvider } from "./lib/session";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 5_000 } },
});

const saved = localStorage.getItem("athar-theme");
if (saved === "dark") document.documentElement.dataset.theme = "dark";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
