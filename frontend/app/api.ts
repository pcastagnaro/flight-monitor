const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
export async function read(path: string, options?: RequestInit) {
  const r = await fetch(`${API}/api${path}`, { cache: "no-store", ...options });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const message = Array.isArray(body.detail)
      ? body.detail
          .map((x: any) => `${x.loc?.slice(1).join(".")}: ${x.msg}`)
          .join("; ")
      : body.detail;
    throw new Error(message || `Error ${r.status} al consultar el servidor`);
  }
  return r.json();
}
