export async function api<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* corps non JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

export function postJson<T = unknown>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return api<T>(path, body === undefined ? { method } : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

export const patchJson = <T = unknown>(path: string, body: unknown) => send<T>("PATCH", path, body);
export const putJson = <T = unknown>(path: string, body: unknown) => send<T>("PUT", path, body);
export const del = <T = unknown>(path: string) => send<T>("DELETE", path);
export const post = <T = unknown>(path: string, body?: unknown) => send<T>("POST", path, body ?? {});
