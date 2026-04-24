// Token lives only in JS heap — invisible to localStorage enumeration,
// cleared on page reload (refresh cookie re-hydrates it via layout.tsx)
let _token: string | null = null

export function saveToken(token: string): void {
  _token = token
}

export function getToken(): string | null {
  return _token
}

export function clearToken(): void {
  _token = null
}

export function isAuthenticated(): boolean {
  return _token !== null
}
