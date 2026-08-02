import { createRoot } from "react-dom/client";
import "@cloudflare/kumo/styles/standalone";
import "./styles.css";
import App from "./App";

document.documentElement.dataset.mode = "dark";

createRoot(document.getElementById("root")!).render(<App />);
