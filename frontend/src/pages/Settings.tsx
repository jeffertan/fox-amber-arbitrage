import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const EDITABLE = [
  { section: 'thresholds', key: 'sell_threshold', label: '卖出触发价', unit: '$/kWh', type: 'number' as const },
  { section: 'thresholds', key: 'night_cheap_buy', label: '夜间便宜充电价', unit: '$/kWh', type: 'number' as const },
  { section: 'thresholds', key: 'min_profit_margin', label: '最低利润边际', unit: '$/kWh', type: 'number' as const },
  { section: 'thresholds', key: 'buy_high', label: '买入价偏高提醒', unit: '$/kWh', type: 'number' as const },
  { section: 'thresholds', key: 'sell_notify', label: '卖出价提醒', unit: '$/kWh', type: 'number' as const },
  { section: 'thresholds', key: 'alert_delta', label: '价格变动提醒幅度', unit: '$/kWh', type: 'number' as const },
  { section: 'battery', key: 'night_reserve_soc', label: '夜间 SOC 底线', unit: '%', type: 'number' as const },
  { section: 'battery', key: 'night_target_soc', label: '夜间充电目标 SOC', unit: '%', type: 'number' as const },
  { section: 'battery', key: 'max_charge_kw', label: '最大充电功率', unit: 'kW', type: 'number' as const },
  { section: 'battery', key: 'max_discharge_kw', label: '最大放电功率', unit: 'kW', type: 'number' as const },
  { section: 'schedule', key: 'day_start', label: '白天开始时间', unit: 'HH:MM', type: 'text' as const },
  { section: 'schedule', key: 'night_start', label: '夜间开始时间', unit: 'HH:MM', type: 'text' as const },
  { section: 'schedule', key: 'max_grid_charge_hour', label: '电网充电截止', unit: '小时 (0-23)', type: 'number' as const },
  { section: 'control', key: 'poll_interval_seconds', label: '轮询间隔', unit: '秒', type: 'number' as const },
  { section: 'control', key: 'manual_override_minutes', label: '手动覆盖持续时间', unit: '分钟', type: 'number' as const },
] as const

export default function Settings() {
  const [cfg, setCfg] = useState<Record<string, Record<string, unknown>> | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Record<string, string>>({})
  const [resetting, setResetting] = useState(false)
  const [resetMsg, setResetMsg] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({})

  useEffect(() => { api.getConfig().then(setCfg) }, [])

  const handleReset = async () => {
    if (!confirmReset) { setConfirmReset(true); return }
    setResetting(true)
    setResetMsg('')
    try {
      const { defaults } = await api.resetConfig()
      const fresh = await api.getConfig()
      setCfg(fresh)
      // Sync input values to newly loaded defaults
      for (const { section, key } of EDITABLE) {
        const k = `${section}.${key}`
        const el = inputRefs.current[k]
        if (el && defaults[section]?.[key] !== undefined) {
          el.value = String(defaults[section][key])
        }
      }
      setResetMsg('✓ 已恢复默认设置')
    } catch (e: unknown) {
      setResetMsg(`错误: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setResetting(false)
      setConfirmReset(false)
      setTimeout(() => setResetMsg(''), 3000)
    }
  }

  if (!cfg) return <div className="text-gray-400 p-8 text-center">加载中...</div>

  const save = async (section: string, key: string, type: string) => {
    const k = `${section}.${key}`
    const raw = inputRefs.current[k]?.value ?? ''
    const value = type === 'number' ? parseFloat(raw) : raw
    if (type === 'number' && isNaN(value as number)) {
      setMsgs(m => ({ ...m, [k]: '请输入有效数字' }))
      return
    }
    setSaving(k)
    try {
      await api.updateConfig(section, key, value)
      setCfg(c => c ? { ...c, [section]: { ...c[section], [key]: value } } : c)
      setMsgs(m => ({ ...m, [k]: '✓ 已保存' }))
      setTimeout(() => setMsgs(m => { const n = { ...m }; delete n[k]; return n }), 2000)
    } catch (e: unknown) {
      setMsgs(m => ({ ...m, [k]: `错误: ${e instanceof Error ? e.message : String(e)}` }))
    } finally {
      setSaving(null)
    }
  }

  const sections: Record<string, string> = {
    thresholds: '价格阈值',
    battery: '电池参数',
    schedule: '时段配置',
    control: '控制设置',
  }

  const grouped = EDITABLE.reduce<Record<string, typeof EDITABLE[number][]>>((acc, f) => {
    if (!acc[f.section]) acc[f.section] = []
    acc[f.section].push(f)
    return acc
  }, {})

  return (
    <div className="space-y-6 max-w-lg">
      <div className="flex items-center justify-between">
        <h2 className="text-white text-lg font-semibold">策略参数配置</h2>
        <div className="flex items-center gap-2">
          {resetMsg && (
            <span className={`text-xs ${resetMsg.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>
              {resetMsg}
            </span>
          )}
          {confirmReset ? (
            <>
              <span className="text-yellow-400 text-xs">确认恢复？</span>
              <button
                onClick={handleReset}
                disabled={resetting}
                className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs transition-colors"
              >
                {resetting ? '恢复中...' : '确认'}
              </button>
              <button
                onClick={() => setConfirmReset(false)}
                className="bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg text-xs transition-colors"
              >
                取消
              </button>
            </>
          ) : (
            <button
              onClick={handleReset}
              className="bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white px-3 py-1.5 rounded-lg text-xs transition-colors"
            >
              恢复默认设置
            </button>
          )}
        </div>
      </div>
      {Object.entries(grouped).map(([section, fields]) => (
        <div key={section} className="space-y-2">
          <h3 className="text-gray-400 text-xs uppercase tracking-wider font-medium">{sections[section] ?? section}</h3>
          {fields.map(({ key, label, unit, type }) => {
            const k = `${section}.${key}`
            const val = cfg[section]?.[key] ?? ''
            const isSaving = saving === k
            const msg = msgs[k]
            return (
              <div key={k} className="bg-gray-900 rounded-xl p-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <label className="text-gray-300 text-sm block mb-1">{label}</label>
                    <div className="flex gap-2 items-center">
                      <input
                        ref={el => { inputRefs.current[k] = el }}
                        type={type}
                        defaultValue={String(val)}
                        step={type === 'number' ? 'any' : undefined}
                        className="w-28 bg-gray-800 text-white rounded-lg px-3 py-1.5 text-sm outline-none border border-gray-700 focus:border-blue-500 transition-colors"
                        onKeyDown={e => e.key === 'Enter' && save(section, key, type)}
                      />
                      <span className="text-gray-500 text-xs">{unit}</span>
                    </div>
                  </div>
                  <button
                    disabled={isSaving}
                    onClick={() => save(section, key, type)}
                    className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-sm transition-colors shrink-0"
                  >
                    {isSaving ? '...' : '保存'}
                  </button>
                </div>
                {msg && (
                  <p className={`text-xs mt-1 ${msg.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>{msg}</p>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
