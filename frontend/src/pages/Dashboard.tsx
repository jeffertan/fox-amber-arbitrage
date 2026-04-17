import { useEffect, useState } from 'react'
import { api } from '../api'
import type { StatusResponse, ForecastPoint } from '../api'
import BatteryGauge from '../components/BatteryGauge'
import PowerFlow from '../components/PowerFlow'
import ControlPanel from '../components/ControlPanel'

const modeColors: Record<string, string> = {
  force_charge: 'text-blue-400',
  force_discharge: 'text-orange-400',
  self_use: 'text-green-400',
}

const modeLabels: Record<string, string> = {
  force_charge: '强制充电',
  force_discharge: '强制放电',
  self_use: '自用模式',
}

function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      {title && <div className="text-gray-400 text-xs font-medium uppercase tracking-wider mb-3">{title}</div>}
      {children}
    </div>
  )
}

function OverrideBanner({ active, action, remaining_minutes, onCancel }: {
  active: boolean; action?: string; remaining_minutes?: number; onCancel: () => void
}) {
  if (!active) return null
  const label = action === 'force_charge' ? '强制充电' : action === 'force_discharge' ? '强制放电' : action
  return (
    <div className="flex items-center justify-between bg-yellow-950 border border-yellow-800 rounded-xl px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="text-yellow-400 text-sm">🔒 手动覆盖中</span>
        <span className="text-yellow-300 text-sm font-medium">{label}</span>
        <span className="text-yellow-600 text-xs">— 自动策略已暂停，剩余约 {remaining_minutes} 分钟</span>
      </div>
      <button
        onClick={onCancel}
        className="text-xs bg-yellow-800 hover:bg-yellow-700 text-yellow-200 px-3 py-1 rounded-lg transition-colors"
      >
        立即恢复自动
      </button>
    </div>
  )
}

function ForecastStrip({ points }: { points: ForecastPoint[] }) {
  if (points.length === 0) return null
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {points.slice(0, 6).map((p, i) => {
        const t = new Date(p.t).toLocaleTimeString('zh-AU', { hour: '2-digit', minute: '2-digit' })
        const income = p.sell >= 0.10
        const spike = p.is_spike
        return (
          <div key={i} className={`flex-shrink-0 rounded-lg px-3 py-2 text-center min-w-[72px] border ${
            spike ? 'border-orange-600 bg-orange-950' :
            income ? 'border-green-800 bg-green-950' :
            'border-gray-800 bg-gray-800'
          }`}>
            <div className="text-gray-400 text-xs">{t}</div>
            <div className={`text-sm font-mono font-bold mt-0.5 ${
              spike ? 'text-orange-400' : income ? 'text-green-400' : 'text-gray-400'
            }`}>
              ${p.sell.toFixed(3)}
            </div>
            {spike && <div className="text-orange-500 text-xs">SPIKE</div>}
          </div>
        )
      })}
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState<StatusResponse | null>(null)
  const [forecast, setForecast] = useState<ForecastPoint[]>([])
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const refresh = async () => {
    try {
      const d = await api.status()
      setData(d)
      setLastUpdated(new Date())
      setError('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const loadForecast = async () => {
    try { setForecast(await api.forecast(3)) } catch { /* silent */ }
  }

  const cancelOverride = async () => {
    await api.cancelOverride()
    await refresh()
  }

  useEffect(() => {
    refresh()
    loadForecast()
    const id = setInterval(refresh, 30_000)
    const fid = setInterval(loadForecast, 300_000) // refresh forecast every 5 min
    return () => { clearInterval(id); clearInterval(fid) }
  }, [])

  if (error) return <div className="text-red-400 bg-red-950 rounded-xl p-4">{error}</div>
  if (!data) return <div className="text-gray-400 p-8 text-center">加载中...</div>

  const { prices, inverter, decision, override } = data

  return (
    <div className="space-y-4">
      {/* Manual override banner */}
      <OverrideBanner
        active={override?.active ?? false}
        action={override?.action}
        remaining_minutes={override?.remaining_minutes}
        onCancel={cancelOverride}
      />

      {/* Price row */}
      <div className="grid grid-cols-2 gap-4">
        <Card title="买入价">
          <div className={`text-2xl font-mono font-bold ${prices && prices.buy_kwh < 0 ? 'text-green-400' : 'text-white'}`}>
            ${prices ? prices.buy_kwh.toFixed(4) : '—'}
            <span className="text-sm text-gray-500 font-normal">/kWh</span>
          </div>
          {prices && prices.buy_kwh < 0 && (
            <div className="text-green-400 text-xs mt-1">⚡ 负电价，电网付钱</div>
          )}
        </Card>
        <Card title="卖出收入">
          <div className={`text-2xl font-mono font-bold ${prices && prices.sell_kwh < 0 ? 'text-yellow-400' : 'text-red-400'}`}>
            ${prices ? Math.abs(prices.sell_kwh).toFixed(4) : '—'}
            <span className="text-sm text-gray-500 font-normal">/kWh</span>
          </div>
          {prices && prices.spike_status !== 'none' && (
            <div className="text-orange-400 text-xs mt-1">⚡ SPIKE: {prices.spike_status}</div>
          )}
          {prices && prices.sell_kwh > 0 && (
            <div className="text-red-400 text-xs mt-1">⚠️ 出口需付费</div>
          )}
        </Card>
      </div>

      {/* Forecast strip */}
      {forecast.length > 0 && (
        <Card title="卖出价预测 (3小时)">
          <ForecastStrip points={forecast} />
        </Card>
      )}

      {/* Battery + Power flow */}
      {inverter && (
        <Card title="逆变器状态">
          <div className="flex gap-4 items-center">
            <BatteryGauge soc={inverter.soc} />
            <div className="flex-1">
              <PowerFlow
                pv={inverter.pv_kw}
                grid={inverter.grid_kw}
                load={inverter.load_kw}
                battery={inverter.battery_kw}
              />
            </div>
          </div>
          <div className="flex gap-4 mt-3 text-xs text-gray-500">
            <span>模式: <span className="text-gray-300">{inverter.work_mode}</span></span>
            <span>电池温度: <span className="text-gray-300">{inverter.battery_temp.toFixed(1)}°C</span></span>
          </div>
        </Card>
      )}

      {/* Decision */}
      {decision && (
        <Card title="当前策略决策">
          <div className="flex items-center gap-2">
            <div className={`text-lg font-semibold ${modeColors[decision.action] ?? 'text-white'}`}>
              {modeLabels[decision.action] ?? decision.action}
            </div>
            {override?.active && (
              <span className="text-xs bg-yellow-900 text-yellow-400 px-2 py-0.5 rounded-full">已暂停</span>
            )}
          </div>
          <div className="text-gray-400 text-sm mt-1">{decision.reason}</div>
          <div className="mt-2 flex gap-4 text-xs text-gray-500">
            <span>平均充电成本: <span className="text-gray-300">${decision.avg_charge_cost.toFixed(4)}/kWh</span></span>
            <span>{new Date(decision.timestamp).toLocaleTimeString('zh-AU')}</span>
          </div>
        </Card>
      )}

      {/* Control */}
      <Card>
        <ControlPanel currentSoc={inverter?.soc} onAction={refresh} />
      </Card>

      {lastUpdated && (
        <p className="text-gray-600 text-xs text-right">
          最后更新: {lastUpdated.toLocaleTimeString('zh-AU')} · 每30秒自动刷新
        </p>
      )}
    </div>
  )
}
