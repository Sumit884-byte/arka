import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import App from "./App";
import "highlight.js/styles/github-dark.min.css";
import "./styles/global.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
      <Toaster theme="dark" position="bottom-right" richColors closeButton />
    </BrowserRouter>
  </StrictMode>,
);
