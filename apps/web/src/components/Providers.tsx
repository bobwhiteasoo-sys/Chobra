"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";

import { ToastProvider } from "./ui";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            networkMode: "always",
            refetchOnWindowFocus: false,
            retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
          },
        },
      }),
  );
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      void navigator.serviceWorker.register("/sw.js");
    }
  }, []);
  return (
    <QueryClientProvider client={client}>
      <Tooltip.Provider delayDuration={300}>
        <ToastProvider>{children}</ToastProvider>
      </Tooltip.Provider>
    </QueryClientProvider>
  );
}
