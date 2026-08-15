export type JobStatus = {
  running: boolean;
  started_at?: number | null;
  finished_at?: number | null;
  target_count: number;
  workers: number;
  source: string;
  last_error?: string;
  log_count: number;
  latest_log_id: number;
  completed_count: number;
  success_count: number;
  failure_count: number;
  progress_percent: number;
  current_stage: string;
  current_email: string;
  batch_id?: string;
};

export type AccountRecord = {
  id: number;
  email: string;
  password: string;
  status: string;
  success: boolean;
  provider: string;
  auth_info: string;
  auth_path: string;
  email_account_id: string;
  email_disable_status: string;
  email_disabled_at: string;
  email_disable_error: string;
  account_file: string;
  failure_type: string;
  failure_reason: string;
  screenshot_path: string;
  screenshot_url: string;
  exception_traceback: string;
  exception_type: string;
  has_exception_traceback: boolean;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  batch_id: string;
  source: string;
  worker_id: number;
  bot_risk?: boolean;
  access_token: string;
  account_id: string;
  expire_at: string;
  proxy_file: string;
  resin_status: string;
  extra?: Record<string, unknown>;
};

export type Stats = {
  total: number;
  success: number;
  failure: number;
  skipped: number;
  cancelled: number;
  cpa_success: number;
  cpa_failed: number;
  email_disabled: number;
  email_disable_failed: number;
  today_total: number;
  today_success: number;
  unique_success_emails: number;
  avg_success_seconds: number;
  providers?: Array<{ provider: string; total: number; success: number }>;
};

export type LogItem = {
  id: number;
  time: string;
  message: string;
};

export type AuthState = {
  enabled: boolean;
  setup_required?: boolean;
  authenticated: boolean;
  username: string;
};

export type ConfigFileSnapshot = {
  path: string;
  exists: boolean;
  size: number;
  modified_at: string;
  content: string;
  parse_error: string;
  sensitive_keys: string[];
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });
  let data: any = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok || data?.ok === false) {
    if (response.status === 401 && data?.auth_required) {
      window.dispatchEvent(
        new CustomEvent("ps-auth-required", { detail: { setupRequired: !!data?.setup_required } })
      );
    }
    const detail = data?.detail;
    const detailText = Array.isArray(detail)
      ? detail.map((item: any) => item?.msg || JSON.stringify(item)).join("; ")
      : detail;
    throw new Error(data?.error || detailText || `请求失败 (${response.status})`);
  }
  return data as T;
}

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  authMe: () => request<{ ok: boolean } & AuthState>("/api/auth/me"),
  setup: (username: string, password: string, confirmPassword: string) =>
    request<{ ok: boolean } & AuthState>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ username, password, confirm_password: confirmPassword }),
    }),
  login: (username: string, password: string) =>
    request<{ ok: boolean } & AuthState>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  stats: () => request<{ ok: boolean; stats: Stats; job: JobStatus }>("/api/stats"),
  accounts: (
    params: {
      status?: string;
      emailDisableStatus?: string;
      q?: string;
      batchId?: string;
      botRisk?: string;
      limit?: number;
      offset?: number;
    } = {}
  ) => {
    const sp = new URLSearchParams();
    if (params.status) sp.set("status", params.status);
    if (params.emailDisableStatus) sp.set("email_disable_status", params.emailDisableStatus);
    if (params.q) sp.set("q", params.q);
    if (params.batchId) sp.set("batch_id", params.batchId);
    if (params.botRisk) sp.set("bot_risk", params.botRisk);
    if (params.limit) sp.set("limit", String(params.limit));
    if (params.offset) sp.set("offset", String(params.offset));
    const qs = sp.toString();
    return request<{
      ok: boolean;
      items: AccountRecord[];
      total: number | null;
      count: number;
      has_more?: boolean;
      offset: number;
      limit: number;
    }>(
      `/api/accounts${qs ? `?${qs}` : ""}`
    );
  },
  accountIds: (
    params: {
      status?: string;
      emailDisableStatus?: string;
      q?: string;
      batchId?: string;
      botRisk?: string;
    } = {}
  ) => {
    const sp = new URLSearchParams();
    if (params.status) sp.set("status", params.status);
    if (params.emailDisableStatus) sp.set("email_disable_status", params.emailDisableStatus);
    if (params.q) sp.set("q", params.q);
    if (params.batchId) sp.set("batch_id", params.batchId);
    if (params.botRisk) sp.set("bot_risk", params.botRisk);
    const qs = sp.toString();
    return request<{ ok: boolean; ids: number[]; total: number }>(
      `/api/accounts/select-ids${qs ? `?${qs}` : ""}`
    );
  },
  account: (id: number) => request<{ ok: boolean; item: AccountRecord }>(`/api/accounts/${id}`),
  fetchProxyList: async (accountId: number) => {
    const response = await fetch(`/api/accounts/${accountId}/proxy-list`);
    if (!response.ok) {
      let data: { detail?: unknown; error?: unknown; auth_required?: boolean; setup_required?: boolean } | null = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      if (response.status === 401 && data?.auth_required) {
        window.dispatchEvent(
          new CustomEvent("ps-auth-required", { detail: { setupRequired: !!data?.setup_required } })
        );
      }
      const detailText = typeof data?.detail === "string" ? data.detail : undefined;
      const errorText = typeof data?.error === "string" ? data.error : undefined;
      throw new Error(detailText || errorText || `下载失败 (${response.status})`);
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    return {
      blob: await response.blob(),
      filename: match?.[1] || `proxies-${accountId}.txt`,
    };
  },
  proxyListUrl: (accountId: number) => `/api/accounts/${accountId}/proxy-list`,
  deleteAccounts: (ids: number[], deleteFiles = true) =>
    request<{ ok: boolean; deleted: number; deleted_files: number; side_lines: number; file_errors: string[] }>(
      "/api/accounts/delete",
      { method: "POST", body: JSON.stringify({ ids, delete_files: deleteFiles }) }
    ),
  getConfig: () => request<{ ok: boolean; config: Record<string, any> }>("/api/config"),
  getConfigFile: () => request<{ ok: boolean; file: ConfigFileSnapshot }>("/api/config/file"),
  saveConfig: (config: Record<string, any>) =>
    request<{ ok: boolean; config: Record<string, any>; changed: string[] }>("/api/config", {
      method: "PUT",
      body: JSON.stringify({ config }),
    }),
  job: () => request<{ ok: boolean; job: JobStatus }>("/api/job"),
  logs: (afterId = 0, limit = 500) =>
    request<{ ok: boolean; logs: LogItem[]; job: JobStatus }>(
      `/api/job/logs?after_id=${afterId}&limit=${limit}`
    ),
  startJob: (payload: { count?: number; workers?: number; config?: Record<string, any> }) =>
    request<{ ok: boolean; job: JobStatus }>("/api/job/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  stopJob: () => request<{ ok: boolean; job: JobStatus }>("/api/job/stop", { method: "POST" }),
  killAllBrowsers: () =>
    request<{ ok: boolean; killed: number; profiles_cleaned: number; job: JobStatus }>(
      "/api/browser/kill-all",
      { method: "POST" }
    ),
  connectivity: () =>
    request<{ ok: boolean; items: Array<{ name: string; ok: boolean; detail: string }>; blocked: boolean }>(
      "/api/connectivity",
      { method: "POST" }
    ),
};
