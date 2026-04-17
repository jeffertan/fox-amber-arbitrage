import { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { api } from '../api'
import type { DailyAnalytics, TradeEvent } from '../api'

const ACTION_LABELS: Record<string, string> = {
  force_discharge: '放电',
  force_charge: '充电',
}


function fmt$(v: number) {
  return (v >= 0 ? '+' : '') + '$' + Math.abs(v).toFixed(3)
}

function SummaryCard({ daily }: { daily: DailyAnalytics[] }) {
  const today = new Date().toISOString().slice(0, 10)
  const todayData = daily.find(d => d.date === today)
  const monthStart = new Date().toISOString().slice(0, 7)
  const monthTotal = daily
    .filter(d => d.date.startsWith(monthStart))
    .reduce((sum, d) => sum + d.net_profit, 0)

  const profit = todayData?.net_profit ?? 0

  return (
    <div className="bg-gray-900 rounded-2xl p-4 space-y-3">
      <div className="text-gray-400 text-xs font-medium uppercase tracking-wider">今日收益</div>
      <div className={`text-3xl font-mono font-bold ${profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {fmt$(profit)}
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-gray-500 text-xs">放电收入</div>
          <div className="text-green-400 font-mono">${(todayData?.discharge_revenue ?? 0).toFixed(3)}</div>
          <div className="text-gray-600 text-xs">{(todayData?.discharge_kwh ?? 0).toFixed(2)} kWh</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">充电成本</div>
          <div className="text-blue-400 font-mono">${(todayData?.charge_cost ?? 0).toFixed(3)}</div>
          <div className="text-gray-600 text-xs">{(todayData?.charge_kwh ?? 0).toFixed(2)} kWh</div>
        </div>
      </div>
      <div className="border-t border-gray-800 pt-3 flex justify-between text-sm">
        <span className="text-gray-500">本月累计</span>
        <span className={`font-mono font-semibold ${monthTotal >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {fmt$(monthTotal)}
        </span>
      </div>
    </div>
  )
}

function ProfitChart({ daily }: { daily: DailyAnalytics[] }) {
  const data = daily.slice(-30).map(d => ({
    date: d.date.slice(5),
    profit: parseFloat(d.net_profit.toFixed(3)),
  }))

  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      <div className="text-gray-400 text-xs font-medium uppercase tracking-wider mb-3">每日净收益 (近30天)</div>
      {data.length === 0 ? (
        <div className="text-gray-600 text-sm text-center py-8">暂无交易数据</div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
            <Tooltip
              contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
              formatter={(v: unknown) => [`$${(v as number).toFixed(3)}`, '净收益']}
              labelStyle={{ color: '#9ca3af' }}
            />
            <ReferenceLine y={0} stroke="#374151" />
            <Bar dataKey="profit" radius={[3, 3, 0, 0]}
              fill="#22c55e"
              className="fill-current"
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function TradeRow({ t }: { t: TradeEvent }) {
  const time = new Date(t.timestamp).toLocaleString('zh-AU', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const isDischarge = t.action === ACTION_LABELS.force_discharge || t.action === 'force_discharge'
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-gray-800 last:border-0">
      <div className={`text-xs font-medium px-2 py-0.5 rounded-full ${
        isDischarge ? 'bg-green-950 text-green-400' : 'bg-blue-950 text-blue-400'
      }`}>
        {ACTION_LABELS[t.action] ?? t.action}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-gray-400 text-xs">{time}</div>
        <div className="text-gray-500 text-xs">
          {t.est_kwh.toFixed(3)} kWh · {Math.round(t.duration_sec / 60)}分钟 · ${Math.abs(t.price_kwh).toFixed(4)}/kWh
        </div>
      </div>
      <div className={`font-mono text-sm font-semibold ${t.est_revenue >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {fmt$(t.est_revenue)}
      </div>
    </div>
  )
}

export default function Analytics() {
  const [daily, setDaily] = useState<DailyAnalytics[]>([])
  const [trades, setTrades] = useState<TradeEvent[]>([])
  const [filter, setFilter] = useState<'all' | 'force_discharge' | 'force_charge'>('all')

  useEffect(() => {
    api.analyticsDaily(30).then(setDaily).catch(() => {})
    api.analyticsTrades(30).then(setTrades).catch(() => {})
  }, [])

  const filtered = filter === 'all' ? trades : trades.filter(t => t.action === filter)

  return (
    <div className="space-y-4">
      <SummaryCard daily={daily} />
      <ProfitChart daily={daily} />

      <div className="bg-gray-900 rounded-2xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-gray-400 text-xs font-medium uppercase tracking-wider">交易记录</div>
          <div className="flex gap-1">
            {(['all', 'force_discharge', 'force_charge'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`text-xs px-2.5 py-1 rounded-lg transition-colors ${
                  filter === f ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-white'
                }`}>
                {f === 'all' ? '全部' : f === 'force_discharge' ? '放电' : '充电'}
              </button>
            ))}
          </div>
        </div>
        {filtered.length === 0 ? (
          <div className="text-gray-600 text-sm text-center py-8">
            {trades.length === 0 ? '暂无交易数据 — 系统开始套利后将在此显示' : '无匹配记录'}
          </div>
        ) : (
          filtered.map((t, i) => <TradeRow key={i} t={t} />)
        )}
      </div>
    </div>
  )
}
