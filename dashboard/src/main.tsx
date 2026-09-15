import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

// Dark by default. The night-city effect only renders in dark mode, and this dashboard
// is something you open at 6am -- a white screen is a poor way to start.
document.documentElement.classList.add("dark");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
