"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { api, ApiError, SettlementSuggestions } from "../lib/api";

const money = (amount: number) => `NT$${new Intl.NumberFormat("en-US").format(amount)}`;

export function SettlementConfirmation({ tripId, suggestion, onClose, onRefresh, onFinished }: {
  tripId: string; suggestion: SettlementSuggestions["suggestions"][number]; onClose: () => void;
  onRefresh: () => Promise<void>; onFinished: (message: string) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const id = useId();
  const close = useCallback(() => { if (!pending.current) onClose(); }, [onClose]);
  useLayoutEffect(() => {
    const dialog = ref.current!;
    const cancel = (event: Event) => { event.preventDefault(); close(); };
    dialog.addEventListener("cancel", cancel);
    return () => dialog.removeEventListener("cancel", cancel);
  }, [close]);
  useEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    dialog.showModal();
    dialog.querySelector<HTMLButtonElement>("button")?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      if (trigger?.isConnected && !trigger.hasAttribute("disabled")) trigger.focus();
      else document.querySelector<HTMLAnchorElement>('a[aria-current="page"]')?.focus();
    };
  }, []);

  async function confirm() {
    if (pending.current || uncertain) return;
    pending.current = true;
    setSaving(true);
    ref.current?.focus();
    setError("");
    try {
      const { from_member_id, to_member_id, amount } = suggestion;
      await api.confirmSettlementSuggestion(tripId, { from_member_id, to_member_id, amount });
      await onRefresh();
      onFinished("Settlement confirmed.");
      onClose();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await onRefresh();
        onFinished("This settlement suggestion has changed. Review the current balances and suggestions before confirming again.");
        onClose();
      } else if (cause instanceof ApiError && (cause.status === 0 || cause.status >= 500)) {
        setUncertain(true);
        setError("Could not confirm whether the settlement was saved. Close this dialog and check settlement history before trying again.");
      } else {
        setError((cause as Error).message);
      }
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  return <dialog ref={ref} tabIndex={-1} className="expense-dialog settlement-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onKeyDown={(event) => {
    if (event.key !== "Tab") return;
    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
    const first = buttons[0], last = buttons[buttons.length - 1];
    if (!first) { event.preventDefault(); event.currentTarget.focus(); }
    else if (event.shiftKey ? document.activeElement === first : document.activeElement === last) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  }}>
    <div className="settlement-confirmation-body">
      <h2 id={`${id}-title`}>Mark this transfer as settled?</h2>
      <p id={`${id}-description`}>Confirm that {suggestion.from_display_name} has already transferred <strong>{money(suggestion.amount)}</strong> to {suggestion.to_display_name} outside TripTab.</p>
      <p className="muted">TripTab does not transfer money. This records the settlement and updates Trip balances.</p>
      {error ? <p className="alert" role="alert">{error}</p> : null}
    </div>
    <div className="payment-actions settlement-confirmation-actions">
      <button type="button" disabled={saving} onClick={close}>{uncertain ? "Close" : "Cancel"}</button>
      <button type="button" disabled={saving || uncertain} onClick={() => void confirm()}>{saving ? "Confirming…" : "Confirm settled"}</button>
    </div>
  </dialog>;
}
