import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/jetbrains-mono";
import "./styles/tokens.css";
import "./styles/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { applyTheme, loadTheme } from "./theme";

applyTheme(loadTheme());
const root = document.getElementById("root");
if (!root) throw new Error("elemento #root ausente");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
