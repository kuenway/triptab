"use client";

import { useEffect, useState } from "react";
import { TravelLoadingIllustration } from "./travel-loading-illustration";

export const LOADING_REVEAL_DELAY_MS = 250;
export const COLD_START_MESSAGE_DELAY_MS = 5000;

// Mount only while the authoritative request is unresolved; resolution never waits.
export function LoadingState({ variant }: { variant: "session" | "trips" }) {
  const [visible, setVisible] = useState(false);
  const [coldStart, setColdStart] = useState(false);
  useEffect(() => {
    const reveal = setTimeout(() => setVisible(true), LOADING_REVEAL_DELAY_MS);
    const cold = setTimeout(() => setColdStart(true), COLD_START_MESSAGE_DELAY_MS);
    return () => { clearTimeout(reveal); clearTimeout(cold); };
  }, []);

  return <div className={`loading-state loading-${variant}${visible ? " loading-revealed" : ""}`} role="status" aria-live="polite">
    <div className="loading-surface" aria-hidden="true"><TravelLoadingIllustration /></div>
    <p className={visible ? "muted loading-message" : "sr-only"}>
      {coldStart ? "Starting TripTab…" : "Getting things ready…"}
    </p>
  </div>;
}
