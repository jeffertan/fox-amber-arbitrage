import { useEffect, useState } from 'react'
import { api } from '../api'
import type { StatusResponse, ForecastPoint } from '../api'
import BatteryGauge from '../components/BatteryGauge'
import PowerFlow from '../components/PowerFlow'
import ControlPanel from '../components/ControlPanel'

// ── Action metadata ───────────────────────────────────────────────────────────

const ACTION_META: Record<string, { label: string; icon: string; bg: string; border: string; text: string; dim: string }> = {
  force_charge:    { label: '强制充电中', icon: '🔋', bg: 'bg-blue-950',        border: 'border-blue-800/50',   text: 'text-blue-300',   dim: 'text-blue-600'   },
  force_discharge: { label: '强制放电中', icon: '⚡',  bg: 'bg-amber-950',       border: 'border-amber-800/50',  text: 'text-amber-300',  dim: 'text-amber-600'  },
  self_use:        { label: '自用模式',   icon: '🌞', bg: 'bg-emerald-950/70',  border: 'border-emerald-800/40', text: 'text-emerald-300', dim: 'text-emerald-700' },
}

// ── System status hero card ───────────────────────────────────────────────────

function StatusHero({
  action, reason, isOverride, soc, buyKwh, sellKwh, avgChargeCost, onCancelOverride,
}: {
  action?: string
  reason?: string
  isOverride?: boolean
  soc?: number
  buyKwh?: number
  sellKwh?: number
  avgChargeCost?: number
  onCancelOverride?: () => void
}) {
  const meta = ACTION_META[action ?? 'self_use'] ?? ACTION_META.self_use
  const socColor = soc === undefined ? '#6b7280' : soc > 60 ? '#4ade80' : soc > 30 ? '#facc15' : '#f87171'

  return (
    <div className={`rounded-2xl p-4 border ${meta.bg} ${meta.border} shadow-lg`}>
      {/* Mode header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-3xl leading-none">{meta.icon}</span>
          <div>
            <div className={`text-lg font-bold leading-snug ${meta.text}`}>{meta.label}</div>
            {isOverride && (
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-xs text-yellow-400 font-medium">🔒 手动覆盖中</span>
                {onCancelOverride && (
                  <button
                    onClick={onCancelOverride}
                    className="text-xs text-yellow-600 hover:text-yellow-400 underline underline-offset-2 transition-colors"
                  >
                    取消
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
        {soc !== undefined && (
          <div className="text-right">
            <div className="text-gray-500 text-xs">电池电量</div>
            <div className="text-2xl font-mono font-bold text-white leading-tight">{soc.toFixed(0)}%</div>
          </div>
        )}
      </div>

      {/* SOC progress bar */}
      {soc !== undefined && (
        <div className="mt-3 h-2 bg-gray-800/80 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-1000 ease-out"
            style={{ width: `${soc}%`, backgroundColor: socColor }}
          />
        </div>
      )}

      {/* Decision reason */}
      {reason && (
        <div className={`mt-3 text-xs leading-relaxed ${meta.dim}`}>{reason}</div>
      )}

      {/* Prices row */}
      {(buyKwh !== undefined || sellKwh !== undefined) && (
        <div className="mt-3 pt-3 border-t border-gray-800/60 flex flex-wrap gap-x-6 gap-y-2">
          {buyKwh !== undefined && (
            <div>
              <div className="text-gray-500 text-xs">当前买入价</div>
              <div className={`font-mono font-semibold text-sm ${buyKwh < 0 ? 'text-green-400' : 'text-white'}`}>
                {buyKwh < 0 ? `电网付钱 $${Math.abs(buyKwh).toFixed(4)}` : `$${buyKwh.toFixed(4)}`}
                <span className="text-gray-600 font-normal text-xs">/kWh</span>
              </div>
            </div>
          )}
          {sellKwh !== undefined && (
            <div>
              <div className="text-gray-500 text-xs">
                {sellKwh < 0 ? '卖出收入' : '出口成本'}
              </div>
              <div className={`font-mono font-semibold text-sm ${sellKwh < 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                {sellKwh < 0 ? `+$${Math.abs(sellKwh).toFixed(4)}` : `-$${Math.abs(sellKwh).toFixed(4)}`}
                <span className="text-gray-600 font-normal text-xs">/kWh</span>
              </div>
            </div>
          )}
          {action === 'force_discharge' && avgChargeCost !== undefined && (
            <div>
              <div className="text-gray-500 text-xs">充电均价</div>
              <div className="font-mono text-sm text-gray-400">
                ${avgChargeCost.toFixed(4)}
                <span className="text-gray-600 font-normal text-xs">/kWh</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Skeleton loader ───────────────────────────────────────────────────────────

function HeroSkeleton() {
  return (
    <div className="rounded-2xl p-4 border border-gray-800 bg-gray-900 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gray-800 rounded-full" />
          <div className="w-32 h-6 bg-gray-800 rounded" />
        </div>
        <div className="w-12 h-8 bg-gray-800 rounded" />
      </div>
      <div className="mt-3 h-2 bg-gray-800 rounded-full" />
      <div className="mt-3 w-48 h-3 bg-gray-800 rounded" />
    </div>
  )
}

// ── Forecast strip ────────────────────────────────────────────────────────────

function ForecastStrip({ points }: { points: ForecastPoint[] }) {
  if (points.length === 0) return null
  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      <div className="text-gray-400 text-xs font-medium uppercase tracking-wider mb-3">卖出价预测</div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {points.slice(0, 6).map((p, i) => {
          const t = new Date(p.t).toLocaleTimeString('zh-AU', { hour: '2-digit', minute: '2-digit' })
          const income = p.sell >= 0.10
          const spike = p.is_spike
          return (
            <div
              key={i}
              className={`flex-shrink-0 rounded-xl px-3 py-2.5 text-center min-w-[68px] border transition-colors ${
                spike   ? 'border-orange-600/70 bg-orange-950/80' :
                income  ? 'border-green-700/60 bg-green-950/60' :
                          'border-gray-800 bg-gray-800/50'
              }`}
            >
              <div className="text-gray-400 text-xs">{t}</div>
              <div className={`text-sm font-mono font-bold mt-1 ${
                spike ? 'text-orange-300' : income ? 'text-green-300' : 'text-gray-400'
              }`}>
                ${p.sell.toFixed(3)}
              </div>
              {spike && <div className="text-orange-500 text-xs mt-0.5 font-medium">SPIKE</div>}
              {income && !spike && <div className="text-green-600 text-xs mt-0.5">收入</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main dashboard ────────────────────────────────────────────────────────────

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
    const id  = setInterval(refresh, 30_000)
    const fid = setInterval(loadForecast, 300_000)
    return () => { clearInterval(id); clearInterval(fid) }
  }, [])

  if (error) {
    return (
      <div className="bg-red-950/60 border border-red-800/50 rounded-2xl p-4 text-red-300 text-sm">
        <span className="font-medium">连接失败：</span>{error}
      </div>
    )
  }

  const { prices, inverter, decision, override } = data ?? {}
  const effectiveAction = override?.active ? override.action : decision?.action

  return (
    <div className="space-y-3">

      {/* ── Hero: system status at a glance ── */}
      {!data ? (
        <HeroSkeleton />
      ) : (
        <StatusHero
          action={effectiveAction}
          reason={decision?.reason}
          isOverride={override?.active}
          soc={inverter?.soc}
          buyKwh={prices?.buy_kwh}
          sellKwh={prices?.sell_kwh}
          avgChargeCost={decision?.avg_charge_cost}
          onCancelOverride={override?.active ? cancelOverride : undefined}
        />
      )}

      {/* ── Override banner with remaining time ── */}
      {override?.active && (
        <div className="flex items-center gap-2 bg-yellow-950/50 border border-yellow-800/40 rounded-xl px-3 py-2">
          <span className="text-yellow-500 text-sm">⏱</span>
          <span className="text-yellow-400 text-xs">
            自动策略已暂停，约 <span className="font-semibold">{override.remaining_minutes} 分钟</span>后恢复
          </span>
        </div>
      )}

      {/* ── Forecast ── */}
      {forecast.length > 0 && <ForecastStrip points={forecast} />}

      {/* ── Inverter: battery + power flow ── */}
      {inverter && (
        <div className="bg-gray-900 rounded-2xl p-4">
          <div className="text-gray-400 text-xs font-medium uppercase tracking-wider mb-3">实时能量流</div>
          <div className="flex gap-4 items-start">
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
          <div className="mt-3 flex gap-4 text-xs text-gray-600 border-t border-gray-800 pt-2">
            <span>逆变器: <span className="text-gray-500">{inverter.work_mode}</span></span>
            <span>电池温度: <span className="text-gray-500">{inverter.battery_temp.toFixed(1)}°C</span></span>
          </div>
        </div>
      )}

      {/* ── Manual control ── */}
      <div className="bg-gray-900 rounded-2xl p-4">
        <ControlPanel
          currentSoc={inverter?.soc}
          currentAction={effectiveAction}
          isOverride={override?.active}
          onAction={refresh}
        />
      </div>

      {lastUpdated && (
        <p className="text-gray-700 text-xs text-center pb-1">
          {lastUpdated.toLocaleTimeString('zh-AU')} 更新 · 每30秒自动刷新
        </p>
      )}
    </div>
  )
}
