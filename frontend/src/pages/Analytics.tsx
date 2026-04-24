import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Legend,
} from 'recharts'
import { api } from '../api'
import type { DailyAnalytics, TradeEvent } from '../api'

const ACTION_LABELS: Record<string, string> = {
  force_discharge: '放电',
  force_charge: '充电',
}

function fmt$(v: number) {
  return (v >= 0 ? '+' : '') + '$' + Math.abs(v).toFixed(3)
}

function dayLabel(dateStr: string) {
  const today = new Date().toISOString().slice(0, 10)
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10)
  if (dateStr === today) return '今天'
  if (dateStr === yesterday) return '昨天'
  return dateStr.slice(5) // MM-DD
}

// ── 3-day cards ───────────────────────────────────────────────────────────────

function DayCard({ d }: { d: DailyAnalytics }) {
  const profit = d.net_profit
  const hasActivity = d.charge_kwh > 0 || d.discharge_kwh > 0
  return (
    <div className="bg-gray-900 rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-gray-300 font-medium">{dayLabel(d.date)}</span>
        <span className={`text-sm font-mono font-bold px-2 py-0.5 rounded-lg ${
          profit > 0 ? 'bg-green-950 text-green-400' :
          profit < 0 ? 'bg-red-950 text-red-400' :
          'bg-gray-800 text-gray-500'
        }`}>
          {hasActivity ? fmt$(profit) : '无交易'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="bg-green-950/40 rounded-xl p-2.5">
          <div className="text-green-500 text-xs mb-1">⚡ 放电</div>
          <div className="text-green-400 font-mono font-semibold">
            {d.discharge_kwh > 0 ? `+$${d.discharge_revenue.toFixed(3)}` : '—'}
          </div>
          <div className="text-gray-600 text-xs mt-0.5">{d.discharge_kwh.toFixed(2)} kWh</div>
        </div>
        <div className="bg-blue-950/40 rounded-xl p-2.5">
          <div className="text-blue-500 text-xs mb-1">🔋 充电</div>
          <div className="text-blue-400 font-mono font-semibold">
            {d.charge_kwh > 0 ? `-$${d.charge_cost.toFixed(3)}` : '—'}
          </div>
          <div className="text-gray-600 text-xs mt-0.5">{d.charge_kwh.toFixed(2)} kWh</div>
        </div>
      </div>
    </div>
  )
}

// ── Grouped bar chart ─────────────────────────────────────────────────────────

function ThreeDayChart({ daily }: { daily: DailyAnalytics[] }) {
  const data = daily.slice(-3).map(d => ({
    date: dayLabel(d.date),
    '放电收入': parseFloat(d.discharge_revenue.toFixed(3)),
    '充电成本': parseFloat((-d.charge_cost).toFixed(3)),
    '净收益': parseFloat(d.net_profit.toFixed(3)),
  }))

  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      <div className="text-gray-400 text-xs font-medium uppercase tracking-wider mb-3">
        近3天充放电收支
      </div>
      {data.length === 0 ? (
        <div className="text-gray-600 text-sm text-center py-8">暂无交易数据</div>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#6b7280' }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} axisLine={false}
              tickFormatter={v => `$${v}`} />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
              formatter={(v: unknown, name) => [`$${Math.abs(v as number).toFixed(3)}`, String(name)]}
              labelStyle={{ color: '#9ca3af' }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
            <ReferenceLine y={0} stroke="#374151" />
            <Bar dataKey="放电收入" fill="#22c55e" radius={[3, 3, 0, 0]} />
            <Bar dataKey="充电成本" fill="#3b82f6" radius={[0, 0, 3, 3]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ── Monthly summary ───────────────────────────────────────────────────────────

function MonthlySummary({ daily }: { daily: DailyAnalytics[] }) {
  const monthStart = new Date().toISOString().slice(0, 7)
  const month = daily.filter(d => d.date.startsWith(monthStart))
  const totalProfit = month.reduce((s, d) => s + d.net_profit, 0)
  const totalDischarge = month.reduce((s, d) => s + d.discharge_revenue, 0)
  const totalCharge = month.reduce((s, d) => s + d.charge_cost, 0)

  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      <div className="text-gray-400 text-xs font-medium uppercase tracking-wider mb-3">本月汇总</div>
      <div className="flex items-center gap-4">
        <div>
          <div className="text-gray-500 text-xs">净收益</div>
          <div className={`text-2xl font-mono font-bold ${totalProfit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {fmt$(totalProfit)}
          </div>
        </div>
        <div className="flex-1 grid grid-cols-2 gap-2 text-sm">
          <div>
            <div className="text-gray-500 text-xs">放电总收入</div>
            <div className="text-green-400 font-mono">+${totalDischarge.toFixed(3)}</div>
          </div>
          <div>
            <div className="text-gray-500 text-xs">充电总成本</div>
            <div className="text-blue-400 font-mono">-${totalCharge.toFixed(3)}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Trade row ─────────────────────────────────────────────────────────────────

function TradeRow({ t }: { t: TradeEvent }) {
  const time = new Date(t.timestamp).toLocaleString('zh-AU', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
  const isDischarge = t.action === 'force_discharge'
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-gray-800 last:border-0">
      <div className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${
        isDischarge ? 'bg-green-950 text-green-400' : 'bg-blue-950 text-blue-400'
      }`}>
        {ACTION_LABELS[t.action] ?? t.action}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-gray-400 text-xs">{time}</div>
        <div className="text-gray-500 text-xs">
          {t.est_kwh.toFixed(3)} kWh · {Math.round(t.duration_sec / 60)} 分钟 · ${Math.abs(t.price_kwh).toFixed(4)}/kWh
        </div>
      </div>
      <div className={`font-mono text-sm font-semibold flex-shrink-0 ${
        t.est_revenue >= 0 ? 'text-green-400' : 'text-red-400'
      }`}>
        {fmt$(t.est_revenue)}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

type DayFilter = '1' | '3' | '7'
type ActionFilter = 'all' | 'force_discharge' | 'force_charge'

export default function Analytics() {
  const [daily, setDaily]   = useState<DailyAnalytics[]>([])
  const [trades, setTrades] = useState<TradeEvent[]>([])
  const [dayFilter,    setDayFilter]    = useState<DayFilter>('3')
  const [actionFilter, setActionFilter] = useState<ActionFilter>('all')

  useEffect(() => {
    api.analyticsDaily(30).then(setDaily).catch(() => {})
    api.analyticsTrades(100).then(setTrades).catch(() => {})
  }, [])

  const last3Days = daily.slice(-3)

  const cutoff = new Date(Date.now() - parseInt(dayFilter) * 86400000).toISOString()
  const filtered = trades
    .filter(t => t.timestamp >= cutoff)
    .filter(t => actionFilter === 'all' || t.action === actionFilter)

  return (
    <div className="space-y-4">

      {/* 3-day cards */}
      <div className="grid grid-cols-3 gap-3">
        {last3Days.length === 0
          ? [0, 1, 2].map(i => (
              <div key={i} className="bg-gray-900 rounded-2xl p-4 text-center text-gray-600 text-sm py-8">
                暂无数据
              </div>
            ))
          : last3Days.map(d => <DayCard key={d.date} d={d} />)
        }
      </div>

      {/* Grouped bar chart */}
      <ThreeDayChart daily={daily} />

      {/* Monthly summary */}
      <MonthlySummary daily={daily} />

      {/* Trade list */}
      <div className="bg-gray-900 rounded-2xl p-4">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div className="text-gray-400 text-xs font-medium uppercase tracking-wider">交易记录</div>
          <div className="flex gap-1 flex-wrap">
            {/* Day filter */}
            <div className="flex gap-1 bg-gray-800 rounded-lg p-0.5">
              {(['1', '3', '7'] as DayFilter[]).map(d => (
                <button key={d} onClick={() => setDayFilter(d)}
                  className={`text-xs px-2.5 py-1 rounded-md transition-colors ${
                    dayFilter === d ? 'bg-gray-600 text-white' : 'text-gray-500 hover:text-white'
                  }`}>
                  {d}天
                </button>
              ))}
            </div>
            {/* Action filter */}
            <div className="flex gap-1 bg-gray-800 rounded-lg p-0.5">
              {(['all', 'force_discharge', 'force_charge'] as ActionFilter[]).map(f => (
                <button key={f} onClick={() => setActionFilter(f)}
                  className={`text-xs px-2.5 py-1 rounded-md transition-colors ${
                    actionFilter === f ? 'bg-gray-600 text-white' : 'text-gray-500 hover:text-white'
                  }`}>
                  {f === 'all' ? '全部' : f === 'force_discharge' ? '放电' : '充电'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="text-gray-600 text-sm text-center py-8">
            {trades.length === 0 ? '暂无交易数据 — 系统开始套利后将在此显示' : '该时段无记录'}
          </div>
        ) : (
          filtered.map((t, i) => <TradeRow key={i} t={t} />)
        )}
      </div>
    </div>
  )
}
