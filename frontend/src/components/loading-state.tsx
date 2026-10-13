"use client";

import { useEffect, useState } from "react";

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
    <div className={`loading-surface${variant === "session" ? " panel" : ""}`} aria-hidden="true">
      {variant === "session" ? <>
        <span className="skeleton-bar skeleton-heading" />
        <div className="skeleton-field"><span className="skeleton-bar skeleton-label" /><span className="skeleton-bar skeleton-input" /></div>
        <div className="skeleton-field"><span className="skeleton-bar skeleton-label" /><span className="skeleton-bar skeleton-input" /></div>
        <span className="skeleton-bar skeleton-input" />
        <span className="skeleton-bar skeleton-footer" />
      </> : <div className="skeleton-trip-list">
        {[0, 1].map(row => <div className="skeleton-trip-row" key={row}><span className={`skeleton-bar skeleton-trip-name skeleton-trip-name-${row}`} /><span className="skeleton-bar skeleton-arrow" /></div>)}
      </div>}
    </div>
    <p className={coldStart ? "muted loading-message" : "sr-only"}>
      {coldStart ? "Starting TripTab…" : variant === "session" ? "Loading TripTab" : "Loading your trips"}
    </p>
  </div>;
}
