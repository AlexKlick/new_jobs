// Shared API configuration for frontend
// Use VITE_API_BASE environment variable in production, fallback to localhost dev default

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080';

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}
