interface StatProps {
  label: string
  value: string | number
  sub?: string
  color?: string
}

export default function Stat({ label, value, sub, color = 'text-white' }: StatProps) {
  return (
    <div className="bg-surface-2 rounded-lg p-3">
      <p className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-lg font-bold ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted mt-0.5">{sub}</p>}
    </div>
  )
}
