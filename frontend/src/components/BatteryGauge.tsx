export default function BatteryGauge({ soc }: { soc: number }) {
  const color = soc > 60 ? '#4ade80' : soc > 30 ? '#facc15' : '#f87171'
  const segments = [75, 50, 25]

  return (
    <div className="flex flex-col items-center gap-1">
      {/* Terminal cap */}
      <div className="w-6 h-2 bg-gray-600 rounded-sm" />
      {/* Battery body */}
      <div className="relative w-14 h-28 border-2 border-gray-600 rounded-lg overflow-hidden bg-gray-900">
        {/* Segment guides */}
        {segments.map(s => (
          <div
            key={s}
            className="absolute w-full border-t border-gray-700/60"
            style={{ bottom: `${s}%` }}
          />
        ))}
        {/* Fill */}
        <div
          className="absolute bottom-0 w-full transition-all duration-1000 ease-out"
          style={{ height: `${soc}%`, backgroundColor: color, opacity: 0.8 }}
        />
        {/* Glow overlay when high SOC */}
        {soc > 80 && (
          <div
            className="absolute bottom-0 w-full"
            style={{ height: `${soc}%`, background: `linear-gradient(to top, ${color}30, transparent)` }}
          />
        )}
        {/* Percentage */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-white font-bold text-sm drop-shadow-lg">{soc.toFixed(0)}%</span>
        </div>
      </div>
      <span className="text-gray-500 text-xs">SOC</span>
    </div>
  )
}
