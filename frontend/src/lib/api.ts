export type CurrentUser = { id: string; email: string; display_name: string | null; created_at: string };
export type AuthState = { user: CurrentUser; csrf_token: string };
export const AUTH_EXPIRED_EVENT = "triptab:auth-expired";
let csrfToken: string | null = null; // CSRF only; the session token stays in its HttpOnly cookie.

export type FinancialAudit = {
  status: "active" | "voided";
  void_reason?: string | null;
  void_created_at?: string | null;
  void_created_by_user_id?: string | null;
  replaces_id?: string | null;
  replaced_by_id?: string | null;
};

export type Trip = {
  id: string;
  name: string;
  currency: "TWD";
  currency_scale: 0;
};

export type Traveler = {
  id: string;
  group_id: string;
  display_name: string;
  user_id: string | null;
  role: "owner" | "member";
};

export type TripInvitation = {
  id: string;
  group_id: string;
  target_member_id: string | null;
  target_member_snapshot_id: string;
  created_by_user_id: string;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  accepted_by_user_id: string | null;
  revoked_at: string | null;
  revoked_by_user_id: string | null;
  status: "pending" | "accepted" | "revoked" | "expired";
};
export type InvitationPreview = { trip_name: string; member_display_name: string; expires_at: string };

export function invitationToken(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
  return token && /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
}

export type ExpenseSplit = { member_id: string; amount: number };

export type Expense = FinancialAudit & {
  id: string;
  group_id: string;
  description: string;
  amount: number;
  payer_member_id: string;
  split_strategy: "equal" | "exact";
  splits: ExpenseSplit[];
  occurred_at: string;
  created_at: string;
  created_by_user_id: string;
};

export type Balances = {
  group_id: string;
  currency: "TWD";
  balances: { member_id: string; display_name: string; amount: number }[];
};

export type SettlementSuggestions = {
  group_id: string;
  currency: "TWD";
  suggestions: {
    from_member_id: string;
    from_display_name: string;
    to_member_id: string;
    to_display_name: string;
    amount: number;
  }[];
};

export type SettlementInput = {
  from_member_id: string;
  to_member_id: string;
  amount: number;
  occurred_at: string;
};

export type Settlement = SettlementInput & FinancialAudit & {
  id: string;
  group_id: string;
  from_display_name: string;
  to_display_name: string;
  created_at: string;
  created_by_user_id: string;
};

export type ExpenseInput = {
  description: string;
  amount: number;
  payer_member_id: string;
  occurred_at: string;
} & (
  | { split_strategy: "equal"; participant_member_ids: string[] }
  | { split_strategy: "exact"; splits: ExpenseSplit[] }
);

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, body?: object, method = body ? "POST" : "GET"): Promise<T> {
  const publicRequest = path === "/auth/login" || path === "/auth/register" || path === "/auth/forgot-password" || path === "/auth/reset-password" || path === "/invitations/preview";
  if (method !== "GET" && !publicRequest && !csrfToken) await api.getMe();
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      credentials: "same-origin",
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(method !== "GET" && !publicRequest && csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Could not reach TripTab. Please try again.", 0);
  }
  if (!response.ok) {
    if (response.status === 401 && !publicRequest) {
      csrfToken = null;
      if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).filter(Boolean).join("; ")
          : `Request failed (${response.status}).`;
    throw new ApiError((message || `Request failed (${response.status}).`).replace(/\btraveler(s)?\b/gi, (_word, plural) => plural ? "tripmates" : "tripmate"), response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function authRequest(path: string, input?: object, method?: string): Promise<AuthState> {
  const state = await request<AuthState>(path, input, method);
  csrfToken = state.csrf_token;
  return state;
}

export const api = {
  forgotPassword: (email: string) => request<{ message: string }>("/auth/forgot-password", { email }),
  resetPassword: async (token: string, newPassword: string) => {
    await request<void>("/auth/reset-password", { token, new_password: newPassword });
    csrfToken = null;
    if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  },
  getMe: () => authRequest("/auth/me"),
  updateProfile: (display_name: string | null) => authRequest("/auth/me", { display_name }, "PATCH"),
  changePassword: (current_password: string, new_password: string) => request<void>("/auth/change-password", { current_password, new_password }),
  register: (email: string, password: string, display_name: string) => authRequest("/auth/register", { email, password, display_name }),
  login: (email: string, password: string) => authRequest("/auth/login", { email, password }),
  logout: async () => { await request<void>("/auth/logout", {}); csrfToken = null; },
  listTrips: () => request<Trip[]>("/groups"),
  createTrip: (name: string) => request<Trip>("/groups", { name }),
  getTrip: (id: string) => request<Trip>(`/groups/${id}`),
  listTravelers: (id: string) => request<Traveler[]>(`/groups/${id}/members`),
  addTraveler: (id: string, display_name: string) =>
    request<Traveler>(`/groups/${id}/members`, { display_name }),
  removeTraveler: (id: string, memberId: string) => request<void>(`/groups/${id}/members/${memberId}`, undefined, "DELETE"),
  createInvitation: (id: string, memberId: string) =>
    request<TripInvitation & { token: string }>(`/groups/${id}/members/${memberId}/invitations`, {}),
  listInvitations: (id: string) => request<TripInvitation[]>(`/groups/${id}/invitations`),
  revokeInvitation: (id: string, invitationId: string) =>
    request<TripInvitation>(`/groups/${id}/invitations/${invitationId}/revoke`, {}),
  previewInvitation: (token: string) => request<InvitationPreview>("/invitations/preview", { token }),
  acceptInvitation: (token: string) => request<Traveler>("/invitations/accept", { token }),
  listExpenses: (id: string) => request<Expense[]>(`/groups/${id}/expenses`),
  addExpense: (id: string, expense: ExpenseInput) =>
    request<Expense>(`/groups/${id}/expenses`, expense),
  getBalances: (id: string) => request<Balances>(`/groups/${id}/balances`),
  getSettlementSuggestions: (id: string) =>
    request<SettlementSuggestions>(`/groups/${id}/settlement-suggestions`),
  confirmSettlementSuggestion: (id: string, suggestion: Pick<SettlementInput, "from_member_id" | "to_member_id" | "amount">) =>
    request<Settlement>(`/groups/${id}/settlement-suggestions/confirm`, suggestion),
  recordSettlement: (id: string, payment: SettlementInput) =>
    request<Settlement>(`/groups/${id}/settlements`, payment),
  voidExpense: (id: string, expenseId: string, reason: string) =>
    request<Expense>(`/groups/${id}/expenses/${expenseId}/void`, { reason }),
  correctExpense: (id: string, expenseId: string, reason: string, replacement: ExpenseInput) =>
    request<Expense>(`/groups/${id}/expenses/${expenseId}/corrections`, { reason, replacement }),
  voidSettlement: (id: string, settlementId: string, reason: string) =>
    request<Settlement>(`/groups/${id}/settlements/${settlementId}/void`, { reason }),
  correctSettlement: (id: string, settlementId: string, reason: string, replacement: SettlementInput) =>
    request<Settlement>(`/groups/${id}/settlements/${settlementId}/corrections`, { reason, replacement }),
  listSettlements: (id: string) => request<Settlement[]>(`/groups/${id}/settlements`),
};
