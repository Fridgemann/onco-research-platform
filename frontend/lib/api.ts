import { getToken, saveToken, clearToken } from './auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function doFetch(path: string, options: RequestInit, token: string | null): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
    credentials: 'include',
  })
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let res = await doFetch(path, options, getToken())

  if (res.status === 401) {
    // Attempt silent refresh using the httpOnly refresh cookie
    const refreshRes = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    })

    if (refreshRes.ok) {
      const { access_token } = await refreshRes.json()
      saveToken(access_token)
      res = await doFetch(path, options, access_token)
    } else {
      clearToken()
      if (typeof window !== 'undefined') window.location.href = '/login'
      throw new ApiError(401, 'Session expired')
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`)
  }

  if (res.status === 204) return undefined as T

  return res.json()
}
