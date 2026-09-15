import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

// The theme is dark by default and there is no light variant. A dashboard you open
// before sunrise should not flash white at you, and the blossom palette is built
// against a plum-black ground -- it does not have a light counterpart to fall back to.
document.documentElement.classList.add("dark");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
