export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  requestId: string;

  constructor(status: number, code: string, message: string, details: Record<string, unknown>, requestId: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.split("; ").find((part) => part.startsWith("chobra_csrf="));
  return match ? decodeURIComponent(match.slice("chobra_csrf=".length)) : "";
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? (options.body === undefined ? "GET" : "POST");
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: "same-origin",
    signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(30_000)]) : AbortSignal.timeout(30_000),
    body: options.body === undefined ? undefined : options.body instanceof FormData ? options.body : JSON.stringify(options.body),
  });
  if (!response.ok) {
    let payload: { code?: string; message?: string; details?: Record<string, unknown>; request_id?: string } = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    throw new ApiError(
      response.status,
      payload.code ?? "HTTP_ERROR",
      payload.message ?? `Сервер ответил ${response.status}`,
      payload.details ?? {},
      payload.request_id ?? response.headers.get("X-Request-ID") ?? "",
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Неизвестная ошибка";
}
