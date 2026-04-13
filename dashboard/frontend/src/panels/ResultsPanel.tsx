import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Trophy, TrendingDown, Layers, Zap, ChevronDown, ChevronRight, Activity, Radio } from 'lucide-react'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { useStore } from '../store'
import api from '../api'

// ── Published headline results ────────────────────────────────────────────
const HEADLINE_RESULTS = [
  {
    model: 'LOLM-304M',
    metric: '68.37',
    unit: 'PPL',
    benchmark: 'WikiText-103',
    comparison: '52.2% better than Pythia-410M at matched compute',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
  },
  {
    model: 'LOLM-1.57B',
    metric: '33.2',
    unit: 'PPL',
    benchmark: 'FineWeb-Edu',
    comparison: '15% better than matched baseline (39.1 PPL)',
    color: 'text-violet-400',
    bg: 'bg-violet-500/10',
    border: 'border-violet-500/30',
  },
  {
    model: 'TPU Validation',
    metric: '43%',
    unit: 'faster',
    benchmark: 'Convergence',
    comparison: 'LOLM converges 43% faster than baseline in first 15K steps',
    color: 'text-sky-400',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/30',
  },
]

// ── Ablation results (Table 2) ────────────────────────────────────────────
const ABLATION_DATA = [
  { name: 'Full LOLM', ppl: 59.23, delta: 0.0, color: '#10b981' },
  { name: 'No Memory', ppl: 59.23, delta: 0.0, color: '#6366f1' },
  { name: 'No Regime', ppl: 123.73, delta: 108.9, color: '#f59e0b' },
  { name: 'No SSM (g→1)', ppl: 499.96, delta: 744.1, color: '#ef4444' },
  { name: 'No Gate (g→0.5)', ppl: 595.43, delta: 905.2, color: '#f97316' },
  { name: 'Decoder Only', ppl: 2198.58, delta: 3611.8, color: '#dc2626' },
]

// ── 1.57B Gate Ablation (Table 3) ─────────────────────────────────────────
const GATE_ABLATION = [
  { name: 'Normal (g≈0.71)', ppl: 34.47, note: 'Learned gate', color: '#10b981' },
  { name: 'Latent Only (g=0.0)', ppl: 56130, note: '+162,744%', color: '#f59e0b' },
  { name: 'Surface Only (g=1.0)', ppl: 485165195, note: '+14M x', color: '#ef4444' },
]

// ── Scaling table (Table 4) ───────────────────────────────────────────────
const SCALING_DATA = [
  { params: '20.5M', tokens: '209M', ppl: 167.77, gate_mean: 0.68, regimes_alive: 18 },
  { params: '149M', tokens: '1.52B', ppl: 64.88, gate_mean: 0.72, regimes_alive: 24 },
  { params: '304M', tokens: '3.1B', ppl: 59.23, gate_mean: 0.71, regimes_alive: 26 },
  { params: '1.57B', tokens: '16.1B', ppl: 33.20, gate_mean: 0.71, regimes_alive: 29 },
]

function Section({ title, icon, children, defaultOpen = true }: {
  title: string; icon: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <Card>
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 text-left">
        {open ? <ChevronDown size={14} className="text-muted" /> : <ChevronRight size={14} className="text-muted" />}
        <span className="text-muted">{icon}</span>
        <h3 className="text-sm font-bold text-white">{title}</h3>
      </button>
      {open && <div className="mt-4">{children}</div>}
    </Card>
  )
}

function AblationChart() {
  // Use log scale for display since values span 59 to 2198
  const chartData = ABLATION_DATA.map(d => ({
    ...d,
    logPpl: Math.log10(d.ppl),
  }))

  return (
    <div className="h-64 sm:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="name"
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            angle={-30}
            textAnchor="end"
            interval={0}
            height={60}
          />
          <YAxis
            dataKey="logPpl"
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            tickFormatter={(v: number) => {
              const val = Math.pow(10, v)
              if (val >= 1000) return `${(val / 1000).toFixed(1)}K`
              return val.toFixed(0)
            }}
            label={{ value: 'PPL (log scale)', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{ background: '#1a2235', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#e2e8f0', fontWeight: 'bold' }}
            formatter={(_: any, __: any, props: any) => {
              const d = ABLATION_DATA[props.payload?.index ?? 0]
              return [`${d.ppl.toLocaleString()} PPL (+${d.delta}%)`, 'Perplexity']
            }}
          />
          <Bar dataKey="logPpl" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function ResultsPanel() {
  const liveMetrics = useStore(s => s.liveMetrics)
  const trainingStatus = useStore(s => s.trainingStatus)
  const logLines = useStore(s => s.logLines)
  const [aiAnalysis, setAiAnalysis] = useState<any>(null)

  const lastMetric = liveMetrics[liveMetrics.length - 1]
  const isRunning = trainingStatus?.running

  // Load latest AI analysis
  useEffect(() => {
    api.get('/analysis/latest').then(r => {
      if (r.data.analysis) setAiAnalysis(r.data.analysis)
    }).catch(() => {})
    const interval = setInterval(() => {
      api.get('/analysis/latest').then(r => {
        if (r.data.analysis) setAiAnalysis(r.data.analysis)
      }).catch(() => {})
    }, 30000)
    return () => clearInterval(interval)
  }, [])

  // Parse model info from log
  const modelInfo = (() => {
    const info: Record<string, string> = {}
    for (const line of logLines) {
      if (line.includes('total:')) {
        const m = line.match(/([\d,]+)/)
        if (m) info.params = (parseInt(m[1].replace(/,/g, '')) / 1e9).toFixed(2) + 'B'
      }
      if (line.includes('Global batch:')) {
        const m = line.match(/Global batch:\s*(\d+)/)
        if (m) info.batch = m[1]
      }
      if (line.includes('Chips:')) {
        const m = line.match(/Chips:\s*(\d+)/)
        if (m) info.chips = m[1]
      }
      if (line.includes('fineweb')) info.dataset = 'FineWeb-Edu'
      if (line.includes('Config:')) {
        const m = line.match(/Config:\s*(.+)/)
        if (m) info.config = m[1].trim()
      }
    }
    return info
  })()

  return (
    <div className="space-y-4">
      {/* LIVE ACTIVE TRAINING */}
      <div className="flex items-center gap-3">
        <Activity size={20} className="text-success" />
        <h2 className="text-lg font-bold">Live Training</h2>
        {isRunning && <div className="w-2 h-2 rounded-full bg-success animate-pulse" />}
        <StatusBadge status={isRunning ? 'RUNNING' : 'STOPPED'} />
      </div>

      {(lastMetric || logLines.length > 0) ? (
        <div className="bg-surface border border-success/20 rounded-lg p-4 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <p className="text-[10px] text-muted">Model</p>
              <p className="text-sm font-bold text-white">LOLM {modelInfo.params || '~1B'}</p>
              <p className="text-[10px] text-muted">{modelInfo.dataset || 'FineWeb-Edu'} • {modelInfo.chips || '16'} chips</p>
            </div>
            <div>
              <p className="text-[10px] text-muted">Step</p>
              <p className="text-sm font-bold text-accent">{lastMetric?.step?.toLocaleString() || '—'}</p>
              <p className="text-[10px] text-muted">/ 50,000</p>
            </div>
            <div>
              <p className="text-[10px] text-muted">Loss</p>
              <p className="text-sm font-bold text-success">{lastMetric?.loss?.toFixed(2) || '—'}</p>
              <p className="text-[10px] text-muted">tok: {lastMetric?.loss_tok?.toFixed(2) || '—'}</p>
            </div>
            <div>
              <p className="text-[10px] text-muted">Gate / Regimes</p>
              <p className="text-sm font-bold text-white">{lastMetric?.gate?.toFixed(3) || '—'}</p>
              <p className="text-[10px] text-muted">{lastMetric?.regimes || '—'}/32 codes alive</p>
            </div>
          </div>
          {/* Progress bar */}
          {lastMetric?.step != null && (
            <div>
              <div className="flex justify-between text-[10px] text-muted mb-1">
                <span>{((lastMetric.step / 50000) * 100).toFixed(1)}% complete</span>
                <span>{lastMetric.steps_per_sec ? `${lastMetric.steps_per_sec} steps/s` : ''}</span>
              </div>
              <div className="w-full bg-border rounded-full h-2">
                <div className="bg-success h-2 rounded-full transition-all" style={{ width: `${Math.min(100, (lastMetric.step / 50000) * 100)}%` }} />
              </div>
            </div>
          )}
          {/* AI Analysis Summary */}
          {aiAnalysis?.analysis && (
            <div className="bg-bg rounded p-3 border-l-2 border-accent">
              <div className="flex items-center gap-2 mb-1">
                <Radio size={10} className="text-accent" />
                <span className="text-[10px] text-accent font-semibold">AI Analysis (step {aiAnalysis.step})</span>
              </div>
              <p className="text-[10px] text-gray-400 leading-relaxed line-clamp-4">{aiAnalysis.analysis}</p>
            </div>
          )}
        </div>
      ) : (
        <Card>
          <p className="text-muted text-sm text-center py-4">No active training. Go to Quick Launch to start a run.</p>
        </Card>
      )}

      {/* Divider */}
      <div className="flex items-center gap-3 pt-2">
        <Trophy size={20} className="text-yellow-400" />
        <h2 className="text-lg font-bold">Published Results</h2>
        <span className="text-[10px] text-muted bg-surface-2 px-2 py-0.5 rounded">FROM PAPER</span>
      </div>

      {/* Headline Results Cards */}
      <Section title="Headline Results" icon={<Zap size={16} />}>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {HEADLINE_RESULTS.map((r) => (
            <div key={r.model} className={`${r.bg} border ${r.border} rounded-lg p-4`}>
              <p className="text-[10px] text-muted uppercase tracking-wider mb-1">{r.benchmark}</p>
              <p className="text-xs font-semibold text-white mb-2">{r.model}</p>
              <div className="flex items-baseline gap-1 mb-2">
                <span className={`text-2xl font-bold ${r.color}`}>{r.metric}</span>
                <span className="text-xs text-muted">{r.unit}</span>
              </div>
              <p className="text-[10px] text-muted leading-relaxed">{r.comparison}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Ablation Results (Table 2) */}
      <Section title="Component Ablation (Table 2)" icon={<Layers size={16} />}>
        <p className="text-[10px] text-muted mb-3">
          Removing components from the 304M model. The SSM latent pathway and learned gate are critical.
        </p>
        <AblationChart />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left text-muted py-2 px-2 font-medium">Configuration</th>
                <th className="text-right text-muted py-2 px-2 font-medium">PPL</th>
                <th className="text-right text-muted py-2 px-2 font-medium">Delta</th>
              </tr>
            </thead>
            <tbody>
              {ABLATION_DATA.map((row) => (
                <tr key={row.name} className="border-b border-border/50 hover:bg-surface-2/50">
                  <td className="py-2 px-2 text-white font-medium">{row.name}</td>
                  <td className="py-2 px-2 text-right font-mono" style={{ color: row.color }}>
                    {row.ppl.toLocaleString()}
                  </td>
                  <td className="py-2 px-2 text-right text-muted">
                    {row.delta === 0 ? 'baseline' : `+${row.delta.toLocaleString()}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* 1.57B Gate Ablation (Table 3) */}
      <Section title="1.57B Gate Ablation (Table 3)" icon={<TrendingDown size={16} />}>
        <p className="text-[10px] text-muted mb-3">
          Forcing the gate to extreme values at 1.57B scale. Both surface-only and latent-only modes catastrophically fail.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {GATE_ABLATION.map((row) => (
            <div key={row.name} className="bg-surface-2 border border-border rounded-lg p-3">
              <p className="text-[10px] text-muted mb-1">{row.name}</p>
              <p className="text-xl font-bold font-mono" style={{ color: row.color }}>
                {row.ppl >= 1e6 ? `${(row.ppl / 1e6).toFixed(0)}M` : row.ppl >= 1000 ? `${(row.ppl / 1000).toFixed(1)}K` : row.ppl.toFixed(2)}
              </p>
              <p className="text-[10px] text-muted mt-1">{row.note}</p>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-muted mt-3 italic">
          The learned gate (g approx 0.71) dynamically mixes surface and latent representations. Forcing it destroys performance.
        </p>
      </Section>

      {/* Scaling Table (Table 4) */}
      <Section title="Scaling Progression (Table 4)" icon={<Zap size={16} />}>
        <p className="text-[10px] text-muted mb-3">
          LOLM scales cleanly from 20.5M to 1.57B parameters. PPL drops consistently; gate and regime behavior stabilize.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left text-muted py-2 px-2 font-medium">Params</th>
                <th className="text-right text-muted py-2 px-2 font-medium">Tokens</th>
                <th className="text-right text-muted py-2 px-2 font-medium">PPL</th>
                <th className="text-right text-muted py-2 px-2 font-medium">Gate Mean</th>
                <th className="text-right text-muted py-2 px-2 font-medium">Regimes Alive</th>
              </tr>
            </thead>
            <tbody>
              {SCALING_DATA.map((row) => (
                <tr key={row.params} className="border-b border-border/50 hover:bg-surface-2/50">
                  <td className="py-2 px-2 text-accent font-bold">{row.params}</td>
                  <td className="py-2 px-2 text-right text-white">{row.tokens}</td>
                  <td className="py-2 px-2 text-right text-emerald-400 font-mono font-bold">{row.ppl}</td>
                  <td className="py-2 px-2 text-right text-violet-400 font-mono">{row.gate_mean}</td>
                  <td className="py-2 px-2 text-right text-sky-400 font-mono">{row.regimes_alive}/32</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Visual scaling bar */}
        <div className="mt-4 space-y-2">
          <p className="text-[10px] text-muted font-medium">PPL Reduction Across Scale</p>
          {SCALING_DATA.map((row) => {
            const maxPpl = 167.77
            const width = (row.ppl / maxPpl) * 100
            return (
              <div key={row.params} className="flex items-center gap-3">
                <span className="text-[10px] text-muted w-12 text-right">{row.params}</span>
                <div className="flex-1 h-4 bg-surface-2 rounded overflow-hidden">
                  <div
                    className="h-full rounded transition-all duration-500"
                    style={{
                      width: `${width}%`,
                      background: `linear-gradient(90deg, #6366f1, ${width < 30 ? '#10b981' : '#8b5cf6'})`,
                    }}
                  />
                </div>
                <span className="text-[10px] text-white font-mono w-16 text-right">{row.ppl} PPL</span>
              </div>
            )
          })}
        </div>
      </Section>

      {/* Key Takeaways */}
      <Card>
        <h3 className="text-sm font-bold text-white mb-3">Key Findings</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="bg-emerald-500/5 border border-emerald-500/20 rounded p-3">
            <p className="text-[10px] text-emerald-400 font-bold mb-1">SSM is Critical</p>
            <p className="text-[10px] text-muted leading-relaxed">
              Removing the Mamba SSM pathway (gate forced to 1.0) increases PPL by 744%. The latent representation is essential.
            </p>
          </div>
          <div className="bg-violet-500/5 border border-violet-500/20 rounded p-3">
            <p className="text-[10px] text-violet-400 font-bold mb-1">Gate Must Be Learned</p>
            <p className="text-[10px] text-muted leading-relaxed">
              At 1.57B, forcing gate to 1.0 (surface only) yields 485M PPL. The per-dimension learned gate is non-negotiable.
            </p>
          </div>
          <div className="bg-sky-500/5 border border-sky-500/20 rounded p-3">
            <p className="text-[10px] text-sky-400 font-bold mb-1">Memory is Free</p>
            <p className="text-[10px] text-muted leading-relaxed">
              Removing persistent memory adds 0% degradation at 304M. The memory system becomes valuable at larger scales.
            </p>
          </div>
          <div className="bg-amber-500/5 border border-amber-500/20 rounded p-3">
            <p className="text-[10px] text-amber-400 font-bold mb-1">Clean Scaling</p>
            <p className="text-[10px] text-muted leading-relaxed">
              From 20.5M to 1.57B: PPL drops 5x, gate stabilizes at 0.71, regimes alive grow from 18 to 29/32.
            </p>
          </div>
        </div>
      </Card>
    </div>
  )
}
