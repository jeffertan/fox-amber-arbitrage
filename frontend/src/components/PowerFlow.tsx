interface Props {
  pv: number
  grid: number
  load: number
  battery: number
}

function Stat({ label, value, color = 'text-white', suffix = 'kW' }: { label: string; value: number; color?: string; suffix?: string }) {
  return (
    <div className="bg-gray-800 rounded-xl p-3 text-center">
      <div className={`text-lg font-mono font-bold ${color}`}>{value >= 0 ? '' : ''}{value.toFixed(2)}</div>
      <div className="text-gray-400 text-xs mt-0.5">{label} ({suffix})</div>
    </div>
  )
}

export default function PowerFlow({ pv, grid, load, battery }: Props) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Stat label="太阳能" value={pv} color="text-yellow-400" />
      <Stat label="电网" value={grid} color={grid > 0 ? 'text-red-400' : grid < -0.05 ? 'text-green-400' : 'text-gray-400'} />
      <Stat label="家庭负载" value={load} color="text-blue-400" />
      <Stat label="电池" value={battery} color={battery > 0.05 ? 'text-green-400' : battery < -0.05 ? 'text-orange-400' : 'text-gray-400'} />
    </div>
  )
}
