const API_KEY = import.meta.env.VITE_API_KEY ?? "";

export function apiFetch(url, options = {}) {
  return fetch(url, {
    ...options,
    headers: { ...options.headers, "X-Unagi-Key": API_KEY },
  });
}
