import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";

import { createTheme, MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "md",
  fontFamily: "'Inter Variable', system-ui, sans-serif",
  fontFamilyMonospace: "'JetBrains Mono Variable', ui-monospace, monospace",
  headings: { fontFamily: "'Inter Variable', system-ui, sans-serif", fontWeight: "650" },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </StrictMode>,
);
