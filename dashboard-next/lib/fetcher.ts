const fallbackBaseUrl = "http://localhost:8000";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? fallbackBaseUrl).replace(
  /\/$/,
  "",
);

export async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    const detail = body ? `: ${body.slice(0, 220)}` : "";
    throw new Error(`API request failed (${response.status})${detail}`);
  }

  return response.json() as Promise<T>;
}
