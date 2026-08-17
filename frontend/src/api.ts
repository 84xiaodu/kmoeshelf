import type {
  AppSettings,
  AuthResult,
  AuthStatus,
  CheckEnqueue,
  ComicDetails,
  ContentType,
  DownloadFormat,
  DownloadTask,
  DirectoryListing,
  InitializationStrategy,
  KmoeStatus,
  SearchPage,
  PolicyImpact,
  StorageMigration,
  StoragePreview,
  StorageStatus,
  Subscription,
  TaskStatus,
} from "./types";

let csrfToken = "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

export function setCsrfToken(token: string) {
  csrfToken = token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method?.toUpperCase() ?? "GET";
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD"].includes(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    let code: string | undefined;
    try {
      const payload = (await response.json()) as { detail?: string | { code?: string; message?: string } };
      if (typeof payload.detail === "string") message = payload.detail;
      else if (payload.detail) {
        message = payload.detail.message ?? message;
        code = payload.detail.code;
      }
    } catch {
      // Preserve the status-based fallback for non-JSON gateway errors.
    }
    throw new ApiError(message, response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  setup: (password: string) => request<AuthResult>("/api/auth/setup", { method: "POST", body: JSON.stringify({ password }) }),
  login: (password: string) => request<AuthResult>("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) }),
  me: () => request<AuthResult>("/api/auth/me"),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  changePassword: (currentPassword: string, newPassword: string) => request<void>("/api/auth/password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
  kmoeStatus: () => request<KmoeStatus>("/api/kmoe/status"),
  kmoeLogin: (email: string, password: string) => request<KmoeStatus>("/api/kmoe/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  search: (query: string, page = 1) => request<SearchPage>(`/api/kmoe/search?q=${encodeURIComponent(query)}&page=${page}`),
  comic: (id: string) => request<ComicDetails>(`/api/kmoe/comics/${encodeURIComponent(id)}`),
  subscriptions: () => request<Subscription[]>("/api/subscriptions"),
  createSubscription: (body: { remote_id: string; content_types: ContentType[]; download_format: DownloadFormat; initialization_strategy: InitializationStrategy }) => request<Subscription>("/api/subscriptions", { method: "POST", body: JSON.stringify(body) }),
  previewSubscriptionPolicy: (id: number, body: { content_types: ContentType[]; download_format: DownloadFormat; initialization_strategy: InitializationStrategy }) => request<PolicyImpact>(`/api/subscriptions/${id}/policy-preview`, { method: "POST", body: JSON.stringify(body) }),
  editSubscription: (id: number, body: { content_types: ContentType[]; download_format: DownloadFormat; initialization_strategy: InitializationStrategy }) => request<Subscription>(`/api/subscriptions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  setSubscriptionEnabled: (id: number, enabled: boolean) => request<Subscription>(`/api/subscriptions/${id}/${enabled ? "resume" : "pause"}`, { method: "POST" }),
  deleteSubscription: (id: number, cancelPending: boolean) => request<void>(`/api/subscriptions/${id}?cancel_pending=${cancelPending}`, { method: "DELETE" }),
  checkAll: () => request<CheckEnqueue>("/api/checks", { method: "POST" }),
  checkOne: (id: number) => request<CheckEnqueue>(`/api/checks/subscriptions/${id}`, { method: "POST" }),
  downloads: (status?: TaskStatus) => request<DownloadTask[]>(`/api/downloads${status ? `?status=${status}` : ""}`),
  cancelDownload: (id: number) => request<DownloadTask>(`/api/downloads/${id}/cancel`, { method: "POST" }),
  retryDownload: (id: number) => request<DownloadTask>(`/api/downloads/${id}/retry`, { method: "POST" }),
  settings: () => request<AppSettings>("/api/settings"),
  updateSettings: (body: AppSettings) => request<AppSettings>("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
  storageStatus: () => request<StorageStatus>("/api/storage"),
  storageDirectories: (path = "") => request<DirectoryListing>(`/api/storage/directories?path=${encodeURIComponent(path)}`),
  createStorageDirectory: (path: string) => request<DirectoryListing>("/api/storage/directories", { method: "POST", body: JSON.stringify({ path }) }),
  previewStorageMigration: (path: string) => request<StoragePreview>("/api/storage/migrations/preview", { method: "POST", body: JSON.stringify({ path }) }),
  startStorageMigration: (path: string) => request<StorageMigration>("/api/storage/migrations", { method: "POST", body: JSON.stringify({ path }) }),
  currentStorageMigration: () => request<StorageMigration | null>("/api/storage/migrations/current"),
  retryStorageMigration: (id: number) => request<StorageMigration>(`/api/storage/migrations/${id}/retry`, { method: "POST" }),
};

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误";
}
