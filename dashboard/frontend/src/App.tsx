import { useState, useEffect, useCallback, useRef } from 'react'
import { Lock, Menu, X, Bell, Zap, AlertTriangle, AlertCircle, Info } from 'lucide-react'
import { useStore } from './store'
import Sidebar from './components/Sidebar'
import TPUPanel from './panels/TPUPanel'
import ConfigPanel from './panels/ConfigPanel'
import DatasetPanel from './panels/DatasetPanel'
import TrainingPanel from './panels/TrainingPanel'
import CheckpointsPanel from './panels/CheckpointsPanel'
import ExperimentsPanel from './panels/ExperimentsPanel'
import QuickLaunchPanel from './panels/QuickLaunchPanel'
import ResultsPanel from './panels/ResultsPanel'
import ChatPanel from './panels/ChatPanel'
import EvalPanel from './panels/EvalPanel'
import ShipPanel from './panels/ShipPanel'
import api from './api'

// ── Notification Types & Components ───────────────────────────────────────

interface AppNotification {
  id: number
  type: string
  title: string
  message: string
  timestamp: number
  step?: number
}

const NOTIF_ICONS: Record<string, React.ReactNode> = {
  milestone: <Zap size={14} className="text-emerald-400" />,
  error: <AlertCircle size={14} className="text-red-400" />,
  warning: <AlertTriangle size={14} className="text-amber-400" />,
  info: <Info size={14} className="text-sky-400" />,
}

const NOTIF_COLORS: Record<string, string> = {
  milestone: 'border-l-emerald-400',
  error: 'border-l-red-400',
  warning: 'border-l-amber-400',
  info: 'border-l-sky-400',
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenId = useRef(0)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await api.get('/notifications', { params: { limit: 30, since_id: 0 } })
      setNotifications(res.data.notifications || [])
      const newCount = (res.data.notifications || []).filter(
        (n: AppNotification) => n.id > lastSeenId.current
      ).length
      setUnreadCount(newCount)
    } catch {
      // Backend may not have notifications yet
    }
  }, [])

  useEffect(() => {
    fetchNotifications()
    const interval = setInterval(fetchNotifications, 15000)
    return () => clearInterval(interval)
  }, [fetchNotifications])

  // Close dropdown on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleOpen = () => {
    setOpen(!open)
    if (!open && notifications.length > 0) {
      lastSeenId.current = notifications[0].id
      setUnreadCount(0)
    }
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button onClick={handleOpen} className="relative text-muted hover:text-white p-1">
        <Bell size={20} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-96 overflow-y-auto bg-surface border border-border rounded-lg shadow-2xl z-50">
          <div className="px-3 py-2 border-b border-border flex items-center justify-between">
            <h4 className="text-xs font-bold text-white">Notifications</h4>
            <span className="text-[9px] text-muted">{notifications.length} events</span>
          </div>
          {notifications.length === 0 ? (
            <div className="p-6 text-center">
              <Bell size={24} className="text-muted mx-auto mb-2 opacity-30" />
              <p className="text-[10px] text-muted">No notifications yet</p>
              <p className="text-[9px] text-muted mt-1">Events appear during training</p>
            </div>
          ) : (
            <div className="divide-y divide-border/50">
              {notifications.map((n) => (
                <div key={n.id} className={`px-3 py-2 border-l-2 ${NOTIF_COLORS[n.type] || 'border-l-slate-400'} hover:bg-surface-2/50`}>
                  <div className="flex items-center gap-2 mb-0.5">
                    {NOTIF_ICONS[n.type] || <Info size={14} className="text-muted" />}
                    <span className="text-[11px] font-semibold text-white">{n.title}</span>
                    <span className="text-[9px] text-muted ml-auto">{timeAgo(n.timestamp)}</span>
                  </div>
                  <p className="text-[10px] text-muted leading-relaxed pl-5 truncate">{n.message}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AuthGate() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const setAuthenticated = useStore(s => s.setAuthenticated)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    localStorage.setItem('lolm_password', password)
    try {
      await api.get('/auth/verify')
      setAuthenticated(true)
    } catch {
      setError('Invalid password')
      localStorage.removeItem('lolm_password')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg px-4">
      <div className="bg-surface border border-border rounded-lg p-6 sm:p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-accent/20 rounded-full flex items-center justify-center mx-auto mb-3">
            <Lock size={24} className="text-accent" />
          </div>
          <h1 className="text-lg font-bold text-white">LOLM Command Center</h1>
          <p className="text-xs text-muted mt-1">TPU Training Management</p>
        </div>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Enter password"
            className="w-full bg-bg border border-border rounded px-3 py-3 text-sm text-white mb-3"
            autoFocus
          />
          {error && <p className="text-danger text-xs mb-2">{error}</p>}
          <button type="submit"
            className="w-full py-3 bg-accent text-white text-sm font-medium rounded hover:bg-accent-2">
            Enter
          </button>
        </form>
      </div>
    </div>
  )
}

const PANELS: Record<string, React.ComponentType> = {
  tpu: TPUPanel,
  config: ConfigPanel,
  dataset: DatasetPanel,
  training: TrainingPanel,
  checkpoints: CheckpointsPanel,
  eval: EvalPanel,
  experiments: ExperimentsPanel,
  quicklaunch: QuickLaunchPanel,
  results: ResultsPanel,
  chat: ChatPanel,
  ship: ShipPanel,
}

export default function App() {
  const authenticated = useStore(s => s.authenticated)
  const panel = useStore(s => s.panel)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  if (!authenticated) return <AuthGate />

  const PanelComponent = PANELS[panel] || TrainingPanel

  return (
    <div className="flex h-screen bg-bg">
      {/* Mobile header */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-surface border-b border-border px-4 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-accent font-bold text-sm">LOLM</h1>
          <p className="text-muted text-[9px]">COMMAND CENTER</p>
        </div>
        <div className="flex items-center gap-3">
          <NotificationBell />
          <button onClick={() => setMobileMenuOpen(!mobileMenuOpen)} className="text-muted">
            {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </div>

      {/* Mobile overlay menu */}
      {mobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/50" onClick={() => setMobileMenuOpen(false)}>
          <div className="w-52 h-full" onClick={e => e.stopPropagation()}>
            <Sidebar onNavigate={() => setMobileMenuOpen(false)} />
          </div>
        </div>
      )}

      {/* Desktop sidebar */}
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-4 sm:p-6 pt-20 lg:pt-6 relative">
        {/* Desktop notification bell */}
        <div className="hidden lg:block fixed top-4 right-6 z-40">
          <NotificationBell />
        </div>
        <PanelComponent />
      </main>
    </div>
  )
}
