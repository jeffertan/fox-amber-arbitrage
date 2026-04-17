import { useState } from 'react'
import { api } from '../api'

interface Props {
  currentSoc?: number
  onAction?: () => void
}

function SocSlider({ value, onChange, min, max, label, color }: {
  value: number; onChange: (v: number) => void
  min: number; max: number; label: string; color: string
}) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-gray-400">
        <span>{label}</span>
        <span className={`font-mono font-bold ${color}`}>{value}%</span>
      </div>
      <input
        type="range" min={min} max={max} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer bg-gray-700"
      />
      <div className="flex justify-between text-xs text-gray-600">
        <span>{min}%</span><span>{max}%</span>
      </div>
    </div>
  )
}

export default function ControlPanel({ currentSoc, onAction }: Props) {
  const [chargeTarget, setChargeTarget] = useState(95)
  const [dischargeFloor, setDischargeFloor] = useState(25)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const [isError, setIsError] = useState(false)

  const send = async (action: string) => {
    setBusy(action)
    setMsg('')
    try {
      await api.control(action, {
        charge_target_soc: chargeTarget,
        discharge_min_soc: dischargeFloor,
      })
      const labels: Record<string, string> = {
        force_charge: `强制充电 → ${chargeTarget}%`,
        force_discharge: `强制放电 → 底线 ${dischargeFloor}%`,
        self_use: '自用模式',
      }
      setMsg(`✓ 已切换: ${labels[action]}`)
      setIsError(false)
      onAction?.()
    } catch (e: unknown) {
      setMsg(`错误: ${e instanceof Error ? e.message : String(e)}`)
      setIsError(true)
    } finally {
      setBusy(null)
    }
  }

  const chargeBlocked = currentSoc !== undefined && currentSoc >= chargeTarget
  const dischargeBlocked = currentSoc !== undefined && currentSoc <= dischargeFloor

  return (
    <div className="space-y-4">
      <h3 className="text-gray-300 text-sm font-medium">手动控制逆变器</h3>

      {currentSoc !== undefined && (
        <div className="text-xs text-gray-500">
          当前 SOC: <span className="text-gray-300 font-mono font-bold">{currentSoc.toFixed(0)}%</span>
        </div>
      )}

      {/* Force Charge */}
      <div className={`rounded-xl p-3 space-y-3 border ${chargeBlocked ? 'border-yellow-800 bg-yellow-950/30' : 'border-gray-800 bg-gray-800/40'}`}>
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-blue-400">🔋 强制充电</span>
          <button
            disabled={!!busy || chargeBlocked}
            onClick={() => send('force_charge')}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
          >
            {busy === 'force_charge' ? '执行中...' : '启动'}
          </button>
        </div>
        <SocSlider
          value={chargeTarget} onChange={setChargeTarget}
          min={20} max={100}
          label="充电上限 (达到此 SOC 停止充电)"
          color="text-blue-400"
        />
        {chargeBlocked && (
          <div className="flex items-center gap-1.5 text-xs text-yellow-400">
            <span>⚠️</span>
            <span>当前 SOC ({currentSoc.toFixed(0)}%) 已达到或超过设定上限 ({chargeTarget}%)，无需充电</span>
          </div>
        )}
      </div>

      {/* Force Discharge */}
      <div className={`rounded-xl p-3 space-y-3 border ${dischargeBlocked ? 'border-yellow-800 bg-yellow-950/30' : 'border-gray-800 bg-gray-800/40'}`}>
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-orange-400">⚡ 强制放电</span>
          <button
            disabled={!!busy || dischargeBlocked}
            onClick={() => send('force_discharge')}
            className="bg-orange-600 hover:bg-orange-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
          >
            {busy === 'force_discharge' ? '执行中...' : '启动'}
          </button>
        </div>
        <SocSlider
          value={dischargeFloor} onChange={setDischargeFloor}
          min={5} max={80}
          label="放电底线 (低于此 SOC 停止放电)"
          color="text-orange-400"
        />
        {dischargeBlocked && (
          <div className="flex items-center gap-1.5 text-xs text-yellow-400">
            <span>⚠️</span>
            <span>当前 SOC ({currentSoc!.toFixed(0)}%) 已低于或等于设定底线 ({dischargeFloor}%)，不允许放电</span>
          </div>
        )}
      </div>

      {/* Self Use */}
      <button
        disabled={!!busy}
        onClick={() => send('self_use')}
        className="w-full bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white py-2 rounded-xl text-sm font-medium transition-colors"
      >
        {busy === 'self_use' ? '执行中...' : '🌞 恢复自用模式'}
      </button>

      {msg && (
        <p className={`text-xs text-center ${isError ? 'text-red-400' : 'text-green-400'}`}>{msg}</p>
      )}
    </div>
  )
}
