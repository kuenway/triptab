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
};

export type ExpenseSplit = { member_id: string; amount: number };

export type Expense = {
  id: string;
  group_id: string;
  description: string;
  amount: number;
  payer_member_id: string;
  split_strategy: "equal" | "exact";
  splits: ExpenseSplit[];
  occurred_at: string;
  created_at: string;
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

export type Settlement = SettlementInput & {
  id: string;
  group_id: string;
  from_display_name: string;
  to_display_name: string;
  created_at: string;
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

async function request<T>(path: string, body?: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Could not reach TripTab. Check that the backend is running.", 0);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).filter(Boolean).join("; ")
          : `Request failed (${response.status}).`;
    throw new ApiError(message || `Request failed (${response.status}).`, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listTrips: () => request<Trip[]>("/groups"),
  createTrip: (name: string) => request<Trip>("/groups", { name }),
  getTrip: (id: string) => request<Trip>(`/groups/${id}`),
  listTravelers: (id: string) => request<Traveler[]>(`/groups/${id}/members`),
  addTraveler: (id: string, display_name: string) =>
    request<Traveler>(`/groups/${id}/members`, { display_name }),
  listExpenses: (id: string) => request<Expense[]>(`/groups/${id}/expenses`),
  addExpense: (id: string, expense: ExpenseInput) =>
    request<Expense>(`/groups/${id}/expenses`, expense),
  getBalances: (id: string) => request<Balances>(`/groups/${id}/balances`),
  getSettlementSuggestions: (id: string) =>
    request<SettlementSuggestions>(`/groups/${id}/settlement-suggestions`),
  recordSettlement: (id: string, payment: SettlementInput) =>
    request<Settlement>(`/groups/${id}/settlements`, payment),
  listSettlements: (id: string) => request<Settlement[]>(`/groups/${id}/settlements`),
};
