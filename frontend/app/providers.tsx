"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import RecorderDock from "@/components/RecorderDock";
import { RecorderProvider } from "@/lib/recorder";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000 } } })
  );
  // The recorder sits above every route so a meeting keeps recording (and
  // uploading) while the user moves around the app.
  return (
    <QueryClientProvider client={client}>
      <RecorderProvider>
        {children}
        <RecorderDock />
      </RecorderProvider>
    </QueryClientProvider>
  );
}
