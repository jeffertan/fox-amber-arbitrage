const BASE = '/api'

function token() { return localStorage.getItem('token') || '' }

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...opts.headers },
  })
  if (r.status === 401) { localStorage.removeItem('token'); window.location.href = '/'; return Promise.reject('Unauthorized') }
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export interface PriceSnapshot {
  buy_kwh: number
  sell_kwh: number
  spike_status: string
  timestamp: string
}

export interface InverterSnapshot {
  soc: number
  pv_kw: number
  grid_kw: number
  load_kw: number
  battery_kw: number
  battery_temp: number
  work_mode: string
  timestamp: string
}

export interface DecisionSnapshot {
  action: string
  reason: string
  avg_charge_cost: number
  timestamp: string
}

export interface OverrideInfo {
  active: boolean
  action?: string
  until?: string
  remaining_minutes?: number
}

export interface StatusResponse {
  prices: PriceSnapshot | null
  inverter: InverterSnapshot | null
  decision: DecisionSnapshot | null
  override: OverrideInfo
}

export interface HistoryPoint {
  t: string
  buy: number
  sell: number
}

export interface DailyAnalytics {
  date: string
  charge_kwh: number
  charge_cost: number
  discharge_kwh: number
  discharge_revenue: number
  net_profit: number
}

export interface TradeEvent {
  timestamp: string
  action: string
  price_kwh: number
  grid_kw: number
  duration_sec: number
  est_kwh: number
  est_revenue: number
}

export interface ForecastPoint {
  t: string
  sell: number
  is_spike: boolean
}

export const api = {
  login: (password: string) =>
    fetch(BASE + '/login', {
      method: 'POST',
      body: new URLSearchParams({ username: 'admin', password }),
    }).then(r => r.json()),

  status: () => req<StatusResponse>('/status'),
  history: (days = 7) => req<HistoryPoint[]>(`/history?days=${days}`),
  forecast: (hours = 4) => req<ForecastPoint[]>(`/forecast?hours=${hours}`),
  getConfig: () => req<Record<string, Record<string, unknown>>>('/config'),
  updateConfig: (section: string, key: string, value: unknown) =>
    req('/config', { method: 'PUT', body: JSON.stringify({ section, key, value }) }),
  control: (action: string, opts: { discharge_kw?: number; charge_target_soc?: number; discharge_min_soc?: number } = {}) =>
    req('/control', { method: 'POST', body: JSON.stringify({ action, discharge_kw: 5.0, charge_target_soc: 95, discharge_min_soc: 25, ...opts }) }),
  resetConfig: () =>
    req<{ ok: boolean; defaults: Record<string, Record<string, unknown>> }>('/config/reset', { method: 'POST' }),
  cancelOverride: () =>
    req('/override', { method: 'DELETE' }),
  analyticsDaily: (days = 30) => req<DailyAnalytics[]>(`/analytics/daily?days=${days}`),
  analyticsTrades: (limit = 20) => req<TradeEvent[]>(`/analytics/trades?limit=${limit}`),
}
