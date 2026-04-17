import { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { api } from '../api'
import type { HistoryPoint, ForecastPoint } from '../api'

interface ChartPoint {
  t: string
  buy?: number
  sell?: number
  forecast?: number
}

export default function Chart() {
  const [history, setHistory] = useState<ChartPoint[]>([])
  const [forecast, setForecast] = useState<ChartPoint[]>([])
  const [days, setDays] = useState(7)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([api.history(days), api.forecast(4)]).then(([hist, fore]) => {
      setHistory(hist.map((p: HistoryPoint) => ({
        t: new Date(p.t).toLocaleString('zh-AU', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
        buy: parseFloat(p.buy.toFixed(4)),
        sell: parseFloat(p.sell.toFixed(4)),
      })))
      setForecast(fore.map((p: ForecastPoint) => ({
        t: new Date(p.t).toLocaleString('zh-AU', { hour: '2-digit', minute: '2-digit' }),
        forecast: parseFloat(p.sell.toFixed(4)),
      })))
    }).finally(() => setLoading(false))
  }, [days])

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-lg font-semibold">价格走势</h2>
        <div className="flex gap-1">
          {([1, 3, 7] as const).map(d => (
            <button key={d} onClick={() => setDays(d)}
              className={`text-sm px-3 py-1 rounded-lg transition-colors ${days === d ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
              {d}天
            </button>
          ))}
        </div>
      </div>

      {/* History chart */}
      <div className="bg-gray-900 rounded-2xl p-4">
        <div className="text-gray-400 text-xs uppercase tracking-wider mb-3">历史价格 ({days}天)</div>
        {loading ? (
          <div className="h-64 flex items-center justify-center text-gray-500">加载中...</div>
        ) : history.length < 2 ? (
          <div className="h-64 flex items-center justify-center text-gray-500">暂无历史数据（系统启动后将开始记录）</div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={history} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="t" tick={{ fill: '#6b7280', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis
                tick={{ fill: '#6b7280', fontSize: 11 }}
                tickFormatter={v => `$${v.toFixed(2)}`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                labelStyle={{ color: '#e5e7eb', fontSize: 12 }}
                formatter={(v: unknown, name: unknown) => [
                  `$${(v as number).toFixed(4)}/kWh`,
                  name === 'buy' ? '买入价' : '卖出收入',
                ]}
              />
              <Legend formatter={v => v === 'buy' ? '买入价' : '卖出收入'} wrapperStyle={{ color: '#9ca3af', fontSize: 12 }} />
              <ReferenceLine y={0.10} stroke="#4ade80" strokeDasharray="4 2" strokeWidth={0.8} label={{ value: '卖出触发 $0.10', fill: '#4ade80', fontSize: 9 }} />
              <ReferenceLine y={0.50} stroke="#f87171" strokeDasharray="4 2" strokeWidth={0.8} label={{ value: '买入提醒 $0.50', fill: '#f87171', fontSize: 9 }} />
              <Line type="monotone" dataKey="buy" stroke="#f87171" dot={false} strokeWidth={1.5} />
              <Line type="monotone" dataKey="sell" stroke="#4ade80" dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Forecast */}
      {forecast.length > 0 && (
        <div className="bg-gray-900 rounded-2xl p-4">
          <div className="text-gray-400 text-xs uppercase tracking-wider mb-3">卖出价预测 (4小时)</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={forecast} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="t" tick={{ fill: '#6b7280', fontSize: 10 }} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => `$${v.toFixed(2)}`} />
              <Tooltip
                contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                formatter={(v: unknown) => [`$${(v as number).toFixed(4)}/kWh`, '预测卖出收入']}
              />
              <ReferenceLine y={0.10} stroke="#4ade80" strokeDasharray="4 2" strokeWidth={0.8} />
              <Line type="monotone" dataKey="forecast" stroke="#a78bfa" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
