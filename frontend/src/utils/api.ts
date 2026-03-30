const API_KEY: string = process.env.NEXT_PUBLIC_API_KEY ?? "";

export async function apiFetch(
  url: string,
  options?: RequestInit,
): Promise<Response> {
  return fetch(url, {
    ...options,
    headers: { ...options?.headers, "X-Unagi-Key": API_KEY },
  });
}
