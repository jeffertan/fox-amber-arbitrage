interface Props {
  pv: number
  grid: number
  load: number
  battery: number
}

function FlowNode({ icon, label, value, color, tag, tagColor }: {
  icon: string
  label: string
  value: number
  color: string
  tag?: string
  tagColor?: string
}) {
  return (
    <div className="bg-gray-800/60 rounded-xl p-3 text-center border border-gray-700/40">
      <div className="text-xl mb-1 leading-none">{icon}</div>
      <div className={`text-base font-mono font-bold ${color}`}>
        {Math.abs(value).toFixed(2)}
        <span className="text-gray-600 text-xs font-normal ml-0.5">kW</span>
      </div>
      <div className="text-gray-400 text-xs mt-0.5">{label}</div>
      {tag && (
        <div className={`text-xs mt-1 font-medium ${tagColor ?? 'text-gray-500'}`}>{tag}</div>
      )}
    </div>
  )
}

export default function PowerFlow({ pv, grid, load, battery }: Props) {
  const gridTag = grid > 0.05 ? '← 买入' : grid < -0.05 ? '→ 卖出' : '平衡'
  const gridTagColor = grid > 0.05 ? 'text-red-400' : grid < -0.05 ? 'text-green-400' : 'text-gray-500'
  const gridColor = grid > 0.05 ? 'text-red-400' : grid < -0.05 ? 'text-green-400' : 'text-gray-400'

  const batTag = battery > 0.05 ? '↑ 充电' : battery < -0.05 ? '↓ 放电' : '待机'
  const batTagColor = battery > 0.05 ? 'text-blue-400' : battery < -0.05 ? 'text-orange-400' : 'text-gray-500'
  const batColor = battery > 0.05 ? 'text-blue-400' : battery < -0.05 ? 'text-orange-400' : 'text-gray-400'

  return (
    <div className="grid grid-cols-2 gap-2">
      <FlowNode icon="☀️" label="太阳能" value={pv} color="text-yellow-400" tag={pv > 0.05 ? '发电中' : '无输出'} tagColor={pv > 0.05 ? 'text-yellow-600' : 'text-gray-600'} />
      <FlowNode icon="🔌" label="电网" value={grid} color={gridColor} tag={gridTag} tagColor={gridTagColor} />
      <FlowNode icon="🏠" label="家庭负载" value={load} color="text-sky-400" />
      <FlowNode icon="🔋" label="电池" value={battery} color={batColor} tag={batTag} tagColor={batTagColor} />
    </div>
  )
}
