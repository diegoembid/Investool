// Cliente mínimo para el backend. Todas las peticiones que cambian datos llevan la
// cabecera de seguridad que exige el backend.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-Investool-Request": "1",
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `Error ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export type Me = { email: string };

export type ProviderUsage = {
  provider: string;
  configured: boolean;
  month_spent_usd: string;
  month_cap_usd: string;
  calls_by_status: Record<string, number>;
};

export type AICallRow = {
  id: number;
  created_at: string;
  provider: string;
  model: string;
  purpose: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  reserved_usd: string;
  latency_ms: number | null;
  error: string | null;
};

export type Usage = {
  as_of: string;
  ai_enabled: boolean;
  usd_to_eur: string;
  today_spent_usd: string;
  daily_cap_usd: string;
  month_spent_usd: string;
  monthly_cap_usd: string;
  providers: ProviderUsage[];
  recent_calls: AICallRow[];
};

export type SmokeResult = {
  provider: string;
  model: string;
  ok: boolean;
  detail: string;
  cost_usd: string;
  call_id: number | null;
};

export type Health = { status: string; database: string; version: string };

export const api = {
  login: (email: string, password: string, code: string) =>
    request<Me>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, code }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  me: () => request<Me>("/api/auth/me"),
  health: () => request<Health>("/api/health"),
  usage: () => request<Usage>("/api/ai/usage"),
  smokeTest: (provider: string) =>
    request<SmokeResult>(`/api/ai/smoke-test/${provider}`, { method: "POST" }),
};
