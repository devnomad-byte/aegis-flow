import { AppProviders } from "./app/providers/AppProviders";
import { AppShell } from "./shell/AppShell";

export function App() {
  return (
    <AppProviders>
      <AppShell />
    </AppProviders>
  );
}
