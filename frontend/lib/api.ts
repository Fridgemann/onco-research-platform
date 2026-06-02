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
  options: RequestInit & { skipRefresh?: boolean } = {},
): Promise<T> {
  const { skipRefresh, ...fetchOptions } = options
  let res = await doFetch(path, fetchOptions, getToken())

  if (res.status === 401 && !skipRefresh) {
    // Attempt silent refresh using the httpOnly refresh cookie
    const refreshRes = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    })

    if (refreshRes.ok) {
      const { access_token } = await refreshRes.json()
      saveToken(access_token)
      res = await doFetch(path, fetchOptions, access_token)
    } else {
      clearToken()
      if (typeof window !== 'undefined') window.location.href = '/login'
      throw new ApiError(401, 'Session expired')
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body.detail
    const message = Array.isArray(detail)
      ? detail.map((e: { msg: string }) => e.msg).join(', ')
      : (detail ?? `HTTP ${res.status}`)
    throw new ApiError(res.status, message)
  }

  if (res.status === 204) return undefined as T

  return res.json()
}
