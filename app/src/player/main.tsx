import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { PlayerApp } from "./PlayerApp";
import "../styles.css";
import "./player.css";

// Web Audio follows the iPhone's silent switch unless the page declares itself a
// media player. Safari 16.4+ exposes this through the Audio Session API.
const audioSession = (navigator as Navigator & { audioSession?: { type: string } }).audioSession;
if (audioSession) audioSession.type = "playback";

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {
      // Offline use is a convenience; the player works online without it.
    });
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PlayerApp />
  </StrictMode>,
);
