"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { RequireAuth } from "../../../components/auth";
import { TripShell } from "../../../components/trip-shell";

export default function TripLayout({ children }: { children: ReactNode }) {
  const { tripId } = useParams<{ tripId: string }>();
  return <RequireAuth><TripShell key={tripId} tripId={tripId}>{children}</TripShell></RequireAuth>;
}
