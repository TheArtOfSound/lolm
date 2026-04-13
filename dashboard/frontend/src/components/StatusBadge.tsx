const statusColors: Record<string, string> = {
  READY: 'bg-success/20 text-success',
  RUNNING: 'bg-success/20 text-success',
  running: 'bg-success/20 text-success',
  CREATING: 'bg-warning/20 text-warning',
  PREEMPTED: 'bg-danger/20 text-danger',
  STOPPED: 'bg-muted/20 text-muted',
  stopped: 'bg-muted/20 text-muted',
  failed: 'bg-danger/20 text-danger',
  completed: 'bg-accent/20 text-accent',
  UNKNOWN: 'bg-muted/20 text-muted',
}

export default function StatusBadge({ status }: { status: string }) {
  const color = statusColors[status] || statusColors.UNKNOWN
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${color}`}>
      {status}
    </span>
  )
}
