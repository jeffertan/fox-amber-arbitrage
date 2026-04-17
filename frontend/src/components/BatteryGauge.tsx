export default function BatteryGauge({ soc }: { soc: number }) {
  const color = soc > 50 ? '#4ade80' : soc > 25 ? '#facc15' : '#f87171'
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-16 h-32 border-2 border-gray-500 rounded-lg overflow-hidden bg-gray-800">
        <div
          className="absolute bottom-0 w-full transition-all duration-700"
          style={{ height: `${soc}%`, backgroundColor: color }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-white font-bold text-sm drop-shadow">
          {soc.toFixed(0)}%
        </span>
      </div>
      <span className="text-gray-400 text-xs">电池 SOC</span>
    </div>
  )
}
