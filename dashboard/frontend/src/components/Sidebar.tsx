import { Cpu, Settings, Database, Play, Save, FlaskConical, Rocket, Trophy, MessageSquare, BarChart3, Upload } from 'lucide-react'
import { useStore } from '../store'
import type { Panel } from '../types'

const navItems: { id: Panel; label: string; icon: React.ReactNode }[] = [
  { id: 'training', label: 'TRAINING', icon: <Play size={18} /> },
  { id: 'tpu', label: 'TPU', icon: <Cpu size={18} /> },
  { id: 'config', label: 'ARCHITECTURE', icon: <Settings size={18} /> },
  { id: 'dataset', label: 'DATA', icon: <Database size={18} /> },
  { id: 'checkpoints', label: 'CHECKPOINTS', icon: <Save size={18} /> },
  { id: 'eval', label: 'EVALUATE', icon: <BarChart3 size={18} /> },
  { id: 'experiments', label: 'EXPERIMENTS', icon: <FlaskConical size={18} /> },
  { id: 'chat', label: 'CHAT', icon: <MessageSquare size={18} /> },
  { id: 'results', label: 'RESULTS', icon: <Trophy size={18} /> },
  { id: 'ship', label: 'SHIP MODEL', icon: <Upload size={18} /> },
  { id: 'quicklaunch', label: 'QUICK LAUNCH', icon: <Rocket size={18} /> },
]

export default function Sidebar({ onNavigate }: { onNavigate?: () => void } = {}) {
  const panel = useStore(s => s.panel)
  const setPanel = useStore(s => s.setPanel)

  const navigate = (id: Panel) => {
    setPanel(id)
    onNavigate?.()
  }

  return (
    <div className="w-52 bg-surface border-r border-border flex flex-col h-screen">
      <div className="p-4 border-b border-border">
        <h1 className="text-accent font-bold text-sm tracking-wider">LOLM</h1>
        <p className="text-muted text-[10px] mt-0.5">COMMAND CENTER</p>
      </div>
      <nav className="flex-1 py-2">
        {navItems.map(item => (
          <button
            key={item.id}
            onClick={() => navigate(item.id)}
            className={`w-full flex items-center gap-3 px-4 py-2.5 text-xs transition-all
              ${panel === item.id
                ? 'bg-accent/10 text-accent border-r-2 border-accent'
                : 'text-muted hover:text-white hover:bg-surface-2'
              }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </nav>
      <div className="p-4 border-t border-border">
        <p className="text-[9px] text-muted">Qira LLC / LOLM</p>
        <p className="text-[9px] text-muted">v1.0 — TPU Research Cloud</p>
      </div>
    </div>
  )
}
