"use client";

import { useCallback, useEffect, useLayoutEffect, useId, useRef, useState } from "react";
import { Expense, Traveler } from "../lib/api";
import { ExpenseForm } from "./expense-form";

export function ExpenseDialog({ tripId, travelers, expense, onClose, onSaved }: {
  tripId: string; travelers: Traveler[]; expense?: Expense;
  onClose: () => void; onSaved: () => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [draft, updateDraft] = useState({ dirty: false, saving: false });
  const titleId = useId();
  const requestClose = useCallback(() => {
    if (draft.saving) return;
    if (!draft.dirty || window.confirm("Discard this expense draft? Your changes will be lost.")) onClose();
  }, [draft, onClose]);
  useLayoutEffect(() => {
    const dialog = ref.current!;
    function cancel(event: Event) {
      event.preventDefault();
      requestClose();
    }
    // Native cancel does not bubble; handle it directly before Escape closes the dialog.
    dialog.addEventListener("cancel", cancel);
    return () => dialog.removeEventListener("cancel", cancel);
  }, [requestClose]);
  useEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    dialog.showModal();
    dialog.querySelector<HTMLInputElement>("input")?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      if (trigger?.isConnected && trigger !== document.body) trigger.focus();
      else document.querySelector<HTMLButtonElement>(".expense-trigger")?.focus();
    };
  }, []);
  return <dialog ref={ref} className="expense-dialog" aria-labelledby={titleId}>
    <header className="expense-dialog-heading"><h2 id={titleId}>{expense ? "Edit expense" : "Add expense"}</h2><button type="button" disabled={draft.saving} onClick={requestClose} aria-label="Close expense dialog" title="Close">×</button></header>
    <ExpenseForm tripId={tripId} travelers={travelers} {...(expense ? { initialExpense: expense } : {})} onCancel={requestClose} onDraftStateChange={updateDraft} onCreated={async () => { await onSaved(); onClose(); }} />
  </dialog>;
}
