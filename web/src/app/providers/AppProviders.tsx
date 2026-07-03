import { QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

import type { AegisRuntime } from "../runtime";

export function AppProviders({
  children,
  runtime,
}: PropsWithChildren<{ runtime: AegisRuntime }>) {
  return <QueryClientProvider client={runtime.queryClient}>{children}</QueryClientProvider>;
}
