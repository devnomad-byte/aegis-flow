import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";

import { AppProviders } from "./app/providers/AppProviders";
import { createAegisRouter } from "./app/router";
import { createAegisRuntime, type CreateAegisRuntimeInput } from "./app/runtime";

type AppProps = CreateAegisRuntimeInput & {
  initialPath?: string;
};

export function App({ initialPath, ...runtimeInput }: AppProps = {}) {
  const [runtime] = useState(() => createAegisRuntime(runtimeInput));
  const [router] = useState(() => createAegisRouter({ runtime, initialPath }));

  return (
    <AppProviders runtime={runtime}>
      <RouterProvider router={router} context={runtime} />
    </AppProviders>
  );
}
