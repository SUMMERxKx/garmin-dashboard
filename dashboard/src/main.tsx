import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

// Dark only. A dashboard you open before sunrise should not flash white at you, and the
// palette is built against a near-black ground -- there is no light counterpart.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
