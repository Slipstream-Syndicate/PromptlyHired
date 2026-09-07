// In a production build there is no sensible default: the API lives on a
// different host entirely. Falling back to localhost there would fail with an
// opaque network error, so say plainly what is missing instead.
const CONFIGURED_API_URL = import.meta.env.VITE_API_BASE_URL
if (!CONFIGURED_API_URL && import.meta.env.PROD) {
  console.error(
    'VITE_API_BASE_URL is not set. Set it to your deployed API URL ' +
      '(e.g. https://jobtrail-api.onrender.com) in your hosting provider environment ' +
      'variables and redeploy.',
  )
}
export const MISSING_API_URL = !CONFIGURED_API_URL && import.meta.env.PROD
// Trailing slashes would produce "//api/..." once paths are appended.
const BASE_URL = (CONFIGURED_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
const REFRESH_KEY = 'jobtrail.refresh_token'

// The access token is short-lived and kept in memory only. Only the refresh
// token is persisted, so a stolen localStorage value still has to go through
// the rotating-refresh endpoint, which revokes it on use.
let accessToken = null
let refreshInFlight = null

export function getRefreshToken() {
  try {
    return localStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

export function setTokens({ access_token, refresh_token }) {
  accessToken = access_token ?? null
  try {
    if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token)
  } catch {
    /* private mode - session lasts until reload */
  }
}

export function clearTokens() {
  accessToken = null
  try {
    localStorage.removeItem(REFRESH_KEY)
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function parseError(response) {
  let detail = `Request failed (${response.status})`
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') detail = body.detail
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(detail, response.status)
}

async function refreshAccessToken() {
  const token = getRefreshToken()
  if (!token) return false

  // Collapse concurrent 401s into a single refresh call.
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${BASE_URL}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: token }),
      })
      if (!response.ok) {
        clearTokens()
        return false
      }
      setTokens(await response.json())
      return true
    } catch {
      return false
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

async function request(path, { method = 'GET', body, retry = true } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && retry && getRefreshToken()) {
    if (await refreshAccessToken()) {
      return request(path, { method, body, retry: false })
    }
  }
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return null
  return response.json()
}


async function upload(path, file) {
  const form = new FormData()
  form.append('file', file)

  const doFetch = async () => {
    const headers = {}
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    // Do NOT set Content-Type: the browser must add the multipart boundary.
    return fetch(`${BASE_URL}${path}`, { method: 'POST', headers, body: form })
  }

  let response = await doFetch()
  if (response.status === 401 && getRefreshToken() && (await refreshAccessToken())) {
    response = await doFetch()
  }
  if (!response.ok) throw await parseError(response)
  return response.json()
}

function qs(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, value)
  }
  const str = search.toString()
  return str ? `?${str}` : ''
}

export const api = {
  hasSession: () => Boolean(getRefreshToken()),
  restoreSession: refreshAccessToken,

  signup: (payload) => request('/api/auth/signup', { method: 'POST', body: payload }),
  login: (payload) => request('/api/auth/login', { method: 'POST', body: payload }),
  logout: () => {
    const refresh_token = getRefreshToken()
    const done = refresh_token
      ? request('/api/auth/logout', { method: 'POST', body: { refresh_token } }).catch(
          () => null,
        )
      : Promise.resolve()
    clearTokens()
    return done
  },
  me: () => request('/api/auth/me'),

  // --- Jobs (added by pasting a link; there is no feed) ---
  listJobs: () => request('/api/jobs'),
  addJobFromUrl: (url) => request('/api/jobs/from-url', { method: 'POST', body: { url } }),
  addJobFromText: (payload) =>
    request('/api/jobs/from-text', { method: 'POST', body: payload }),
  getJob: (id) => request(`/api/jobs/${id}`),
  // Costs an API call, so it is an explicit POST rather than part of GET.
  analyzeMatch: (id, refresh = false) =>
    request(`/api/jobs/${id}/match${refresh ? '?refresh=true' : ''}`, { method: 'POST' }),

  listSaved: () => request('/api/saved'),
  saveJob: (jobId) => request(`/api/saved/${jobId}`, { method: 'POST' }),
  unsaveJob: (jobId) => request(`/api/saved/${jobId}`, { method: 'DELETE' }),

  // --- Resume + skill profile ---
  getActiveResume: () => request('/api/resumes/active'),
  listResumes: () => request('/api/resumes'),
  uploadResume: (file) => upload('/api/resumes', file),
  reanalyzeResume: (id) => request(`/api/resumes/${id}/analyze`, { method: 'POST' }),
  updateSkillProfile: (id, payload) =>
    request(`/api/resumes/${id}/skill-profile`, { method: 'PATCH', body: payload }),

  // --- Documents + history ---
  generateDocument: (jobId, payload) =>
    request(`/api/jobs/${jobId}/documents`, { method: 'POST', body: payload }),
  getDocument: (id) => request(`/api/documents/${id}`),
  updateDocument: (id, edited_content) =>
    request(`/api/documents/${id}`, { method: 'PATCH', body: { edited_content } }),
  resetDocument: (id) => request(`/api/documents/${id}/reset`, { method: 'POST' }),
  deleteDocument: (id) => request(`/api/documents/${id}`, { method: 'DELETE' }),
  history: () => request('/api/history'),

  // --- Profile ---
  getProfile: () => request('/api/profile'),
  updateProfile: (payload) => request('/api/profile', { method: 'PATCH', body: payload }),
  uploadProfilePicture: (file) => upload('/api/profile/picture', file),
  removeProfilePicture: () => request('/api/profile/picture', { method: 'DELETE' }),
}
