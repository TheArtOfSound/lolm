import { useEffect } from 'react'
import { FlaskConical, BarChart3 } from 'lucide-react'
import Card from '../components/Card'
import { useStore } from '../store'
import api from '../api'

const ABLATION_OPTIONS = [
  { id: 'no-ssm', name: 'No SSM (gate→1)', desc: 'Remove latent SSM path. Paper: +744% PPL at 304M, +14M× at 1.57B.' },
  { id: 'no-gate', name: 'No Gate (gate→0.5)', desc: 'Fixed equal mixing instead of learned per-dim gate. Paper: +905% PPL.' },
  { id: 'no-regime', name: 'No Regime', desc: 'Remove discrete phase detection. Paper: +109% PPL.' },
  { id: 'no-memory', name: 'No Memory', desc: 'Remove persistent memory banks. Paper: +0% at 304M (scale-dependent).' },
  { id: 'no-cpc', name: 'No CPC Loss', desc: 'Remove contrastive predictive coding. SSM has no training signal.' },
  { id: 'no-isolation', name: 'No Gradient Isolation', desc: 'Allow token loss to flow into regime. Paper: causes code collapse in 500-2000 steps.' },
]

export default function ExperimentsPanel() {
  const runs = useStore(s => s.runs)
  const setRuns = useStore(s => s.setRuns)

  useEffect(() => {
    api.get('/runs').then(r => setRuns(r.data.runs || [])).catch(() => {})
  }, [])

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold">Experiments</h2>

      <Card title="Ablation Options">
        <p className="text-[11px] text-muted mb-3">
          Each ablation removes one LOLM component to measure its contribution.
          Results from the paper (Tables 2-3) are shown for reference.
        </p>
        <div className="space-y-2">
          {ABLATION_OPTIONS.map(opt => (
            <div key={opt.id} className="flex items-start gap-3 p-3 rounded bg-surface-2">
              <FlaskConical size={14} className="text-accent mt-0.5" />
              <div className="flex-1">
                <span className="text-xs font-medium text-white">{opt.name}</span>
                <p className="text-[10px] text-muted mt-0.5">{opt.desc}</p>
              </div>
              <button className="px-2 py-1 bg-accent/10 text-accent text-[10px] rounded hover:bg-accent/20">
                Configure
              </button>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Past Runs">
        {runs.length === 0 ? (
          <p className="text-muted text-sm text-center py-8">
            No training runs recorded yet. Runs are logged to Supabase when training is launched from the dashboard.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted text-left">
                  <th className="pb-2 pr-4">Name</th>
                  <th className="pb-2 pr-4">Status</th>
                  <th className="pb-2 pr-4">TPU</th>
                  <th className="pb-2 pr-4">Step</th>
                  <th className="pb-2 pr-4">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(run => (
                  <tr key={run.id} className="border-b border-border/30 hover:bg-surface-2">
                    <td className="py-2 pr-4 text-white">{run.name}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-[10px] ${run.status === 'running' ? 'text-success' : 'text-muted'}`}>
                        {run.status}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-muted">{run.tpu_name}</td>
                    <td className="py-2 pr-4 text-accent">{run.current_step}/{run.max_steps}</td>
                    <td className="py-2 pr-4 text-muted">{new Date(run.started_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
