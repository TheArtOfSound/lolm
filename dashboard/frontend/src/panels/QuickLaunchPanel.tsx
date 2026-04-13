import { useState } from 'react'
import { Rocket, Cpu, Clock, Zap, ChevronRight, Database } from 'lucide-react'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import api from '../api'

const DATASETS = [
  { id: 'HuggingFaceFW/fineweb-edu', name: 'FineWeb-Edu', tokens: '1.3T', desc: 'Curated educational web (LOLM primary)' },
  { id: 'allenai/c4', name: 'C4', tokens: '156B', desc: 'Clean Crawled Corpus' },
  { id: 'togethercomputer/RedPajama-Data-1T', name: 'RedPajama', tokens: '1.2T', desc: 'Open LLaMA replica data' },
  { id: 'roneneldan/TinyStories', name: 'TinyStories', tokens: '~500M', desc: 'Fast ablations (tiny dataset)' },
  { id: 'EleutherAI/pile', name: 'The Pile', tokens: '825GB', desc: 'Diverse 22-domain (Pythia data)' },
  { id: 'bigcode/the-stack', name: 'The Stack', tokens: '6TB', desc: 'Code across 30+ languages' },
]

const SCALE_PRESETS = [
  {
    id: '500m', name: 'LOLM 500M', config: 'configs/scale/500m_lolm_pod.yaml',
    params: '~290M', d: 1024, layers: 16, dff: 4096, ssm: 2, seq: 512, batch: 4,
    time: '~4 hrs', desc: 'Fast iteration. Good for testing architecture changes. Fits on single v4-8.',
    color: 'text-success',
  },
  {
    id: '1b', name: 'LOLM 1B', config: 'configs/scale/1b_lolm_pod.yaml',
    params: '~890M', d: 2048, layers: 16, dff: 5504, ssm: 3, seq: 512, batch: 2,
    time: '~12 hrs', desc: 'Standard pretraining scale. Paper showed 33.2 PPL at 1.57B. 3 SSM layers.',
    color: 'text-accent',
  },
  {
    id: '2b', name: 'LOLM 2B', config: 'configs/scale/2b_lolm_pod.yaml',
    params: '~1.9B', d: 2560, layers: 24, dff: 6912, ssm: 4, seq: 512, batch: 1,
    time: '~1 day', desc: 'Mid-scale with full subsystems. 4 SSM layers, 48 regime codes.',
    color: 'text-accent',
  },
  {
    id: '3b', name: 'LOLM 3B', config: 'configs/scale/3b_lolm_pod.yaml',
    params: '~2.7B', d: 3072, layers: 24, dff: 8192, ssm: 4, seq: 256, batch: 1,
    time: '~2 days', desc: 'Scaled SSM + regime. Seq reduced to 256 for HBM. 4 SSM layers, d_state=64.',
    color: 'text-warning',
  },
  {
    id: '4b', name: 'LOLM 4B', config: 'configs/scale/4b_lolm_pod.yaml',
    params: '~3.9B', d: 3584, layers: 28, dff: 8192, ssm: 2, seq: 256, batch: 1,
    time: '~3 days', desc: 'Large scale. Gradient checkpointing required. 28 decoder layers.',
    color: 'text-warning',
  },
  {
    id: '5b', name: 'LOLM 5B', config: 'configs/scale/7b_lolm_pod.yaml',
    params: '~5.0B', d: 4096, layers: 32, dff: 8192, ssm: 1, seq: 256, batch: 1,
    time: '~4 days', desc: 'Current max for v4-32. Full FSDP (decoder + LM head + SSM projections).',
    color: 'text-danger',
  },
]

export default function QuickLaunchPanel() {
  const [launching, setLaunching] = useState<string | null>(null)
  const [selectedScale, setSelectedScale] = useState<string | null>(null)
  const [selectedDataset, setSelectedDataset] = useState(
    () => localStorage.getItem('lolm_dataset') || DATASETS[0].id
  )

  const handleLaunch = async (preset: typeof SCALE_PRESETS[0]) => {
    const ds = DATASETS.find(d => d.id === selectedDataset) || DATASETS[0]
    if (!confirm(`Launch ${preset.name} (${preset.params})?\n\nDataset: ${ds.name} (${ds.tokens})\nConfig: ${preset.config}\nEstimated time: ${preset.time}\n\nThis will:\n1. SSH to all 4 TPU workers\n2. Pull latest code\n3. Clean old processes\n4. Start training in tmux\n\nTakes ~2 min to launch.`)) return

    setLaunching(preset.id)
    try {
      const res = await api.post('/training/launch', null, {
        params: { tpu_name: 'lolm-7b', config: preset.config, auto_retry: true, dataset: selectedDataset },
        timeout: 300000,
      })
      if (res.data.success) {
        alert(`Training launched! ${res.data.message}\n\nGo to TRAINING panel to monitor.`)
      } else {
        alert(`Launch failed: ${res.data.error}`)
      }
    } catch (e: any) {
      alert(`Error: ${e.message}`)
    }
    setLaunching(null)
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold">Quick Launch</h2>
        <p className="text-xs text-muted mt-1">
          One-click LOLM training at any scale. All configs use the full LOLM architecture
          (Decoder + SSM + Memory + Regime + Gate) sized to fit v4-32 (32GB HBM/chip).
        </p>
      </div>

      {/* Dataset selector */}
      <Card title="1. Choose Dataset">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {DATASETS.map(ds => (
            <button
              key={ds.id}
              onClick={() => setSelectedDataset(ds.id)}
              className={`text-left p-2.5 rounded border transition-all ${
                selectedDataset === ds.id
                  ? 'border-accent bg-accent/10'
                  : 'border-border hover:border-border/80 bg-surface-2'
              }`}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <Database size={10} className={selectedDataset === ds.id ? 'text-accent' : 'text-muted'} />
                <span className="text-xs font-semibold text-white">{ds.name}</span>
              </div>
              <p className="text-[9px] text-muted">{ds.tokens} • {ds.desc}</p>
            </button>
          ))}
        </div>
      </Card>

      {/* Scale selector cards */}
      <Card title="2. Choose Scale">
        <p className="text-[10px] text-muted mb-3">
          Training on <span className="text-accent font-semibold">{DATASETS.find(d => d.id === selectedDataset)?.name || 'FineWeb-Edu'}</span>
        </p>
      </Card>
      <div className="space-y-3">
        {SCALE_PRESETS.map(preset => {
          const isSelected = selectedScale === preset.id
          return (
            <div
              key={preset.id}
              className={`bg-surface border rounded-lg overflow-hidden transition-all cursor-pointer ${
                isSelected ? 'border-accent' : 'border-border hover:border-border/80'
              }`}
              onClick={() => setSelectedScale(isSelected ? null : preset.id)}
            >
              {/* Header row */}
              <div className="flex items-center justify-between p-3">
                <div className="flex items-center gap-3">
                  <div className={`text-xl font-black ${preset.color}`}>
                    {preset.id.toUpperCase()}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">{preset.name}</div>
                    <div className="text-[10px] text-muted">{preset.params} • {preset.time}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={(e) => { e.stopPropagation(); handleLaunch(preset); }}
                    disabled={launching === preset.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/20 text-accent text-xs font-semibold rounded hover:bg-accent/30 disabled:opacity-50"
                  >
                    <Rocket size={12} />
                    {launching === preset.id ? 'Launching...' : 'Launch'}
                  </button>
                  <ChevronRight size={14} className={`text-muted transition-transform ${isSelected ? 'rotate-90' : ''}`} />
                </div>
              </div>

              {/* Expanded details */}
              {isSelected && (
                <div className="px-3 pb-3 border-t border-border/50 pt-3">
                  <p className="text-[11px] text-muted mb-3">{preset.desc}</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px]">
                    <div className="bg-surface-2 rounded p-2">
                      <div className="text-muted">d_model</div>
                      <div className="text-white font-bold">{preset.d}</div>
                    </div>
                    <div className="bg-surface-2 rounded p-2">
                      <div className="text-muted">Layers</div>
                      <div className="text-white font-bold">{preset.layers}</div>
                    </div>
                    <div className="bg-surface-2 rounded p-2">
                      <div className="text-muted">d_ff</div>
                      <div className="text-white font-bold">{preset.dff}</div>
                    </div>
                    <div className="bg-surface-2 rounded p-2">
                      <div className="text-muted">SSM layers</div>
                      <div className="text-white font-bold">{preset.ssm}</div>
                    </div>
                    <div className="bg-surface-2 rounded p-2">
                      <div className="text-muted">Seq len</div>
                      <div className="text-white font-bold">{preset.seq}</div>
                    </div>
                    <div className="bg-surface-2 rounded p-2">
                      <div className="text-muted">Batch/chip</div>
                      <div className="text-white font-bold">{preset.batch}</div>
                    </div>
                    <div className="bg-surface-2 rounded p-2 col-span-2">
                      <div className="text-muted font-mono">{preset.config}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Architecture note */}
      <Card>
        <div className="flex items-start gap-3">
          <Zap size={16} className="text-accent mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-white">All configs are 100% LOLM</p>
            <p className="text-[10px] text-muted mt-1">
              Every scale includes the full architecture: Surface Decoder (pre-norm Transformer + RoPE),
              Latent SSM (Mamba-style), Persistent Memory (3 banks), Regime Layer (Gumbel-Softmax),
              and Manifestation Gate (per-dimension). All 7 training losses active. Auto-retry on OOM
              with reduced params.
            </p>
          </div>
        </div>
      </Card>
    </div>
  )
}
