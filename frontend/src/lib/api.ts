export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: "include", headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function csrfHeaders(): HeadersInit {
  const value = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("darwinspot_csrf="))?.split("=")[1];
  return value ? { "X-DarwinSpot-CSRF": decodeURIComponent(value) } : {};
}
