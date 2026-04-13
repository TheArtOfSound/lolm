import { useEffect, useState, useRef } from 'react'
import { Save, FileText, Info, ChevronDown, ChevronRight, X } from 'lucide-react'
import Card from '../components/Card'
import { useStore } from '../store'
import api from '../api'

// ── Architecture Visualization Component ──────────────────────────────────

const ARCH_COLORS = {
  surface: { bg: '#3b82f6', border: '#60a5fa', label: 'Surface Decoder' },
  ssm: { bg: '#10b981', border: '#34d399', label: 'Latent SSM' },
  memory: { bg: '#f59e0b', border: '#fbbf24', label: 'Persistent Memory' },
  regime: { bg: '#ef4444', border: '#f87171', label: 'Regime Layer' },
  gate: { bg: '#a855f7', border: '#c084fc', label: 'Manifestation Gate' },
  fusion: { bg: '#e2e8f0', border: '#f1f5f9', label: 'Fusion' },
}

interface ArchBoxProps {
  x: number
  y: number
  w: number
  h: number
  color: { bg: string; border: string; label: string }
  label: string
  sublabel: string
  onClick: () => void
}

function ArchBox({ x, y, w, h, color, label, sublabel, onClick }: ArchBoxProps) {
  return (
    <g onClick={onClick} className="cursor-pointer" role="button" tabIndex={0}>
      <rect
        x={x} y={y} width={w} height={h}
        rx={6} ry={6}
        fill={color.bg + '20'}
        stroke={color.border}
        strokeWidth={1.5}
        className="transition-all duration-200 hover:opacity-80"
      />
      <text x={x + w / 2} y={y + h / 2 - 6} textAnchor="middle"
        fill={color.border} fontSize={11} fontWeight="bold" fontFamily="inherit">
        {label}
      </text>
      <text x={x + w / 2} y={y + h / 2 + 8} textAnchor="middle"
        fill="#94a3b8" fontSize={8} fontFamily="inherit">
        {sublabel}
      </text>
    </g>
  )
}

function Arrow({ x1, y1, x2, y2 }: { x1: number; y1: number; x2: number; y2: number }) {
  return (
    <line x1={x1} y1={y1} x2={x2} y2={y2}
      stroke="#475569" strokeWidth={1.2} markerEnd="url(#arrowhead)" />
  )
}

function ArchitectureDiagram({ config }: { config: Record<string, any> | null }) {
  const [tooltip, setTooltip] = useState<{ key: string; x: number; y: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const getConfigValues = (key: string): Record<string, string> => {
    if (!config) return { note: 'Load a config to see values' }
    const m = config.model || {}
    switch (key) {
      case 'surface':
        return {
          'd_model': String(m.d_model ?? 4096),
          'n_layers': String(m.n_layers ?? 32),
          'd_ff': String(m.d_ff ?? 8192),
          'n_heads': String(m.n_heads ?? 32),
          'rope': 'Rotary Position Embedding',
        }
      case 'ssm':
        return {
          'ssm_layers': String(m.ssm_n_layers ?? 4),
          'd_state': String(m.ssm_d_state ?? 64),
          'expand': String(m.ssm_expand ?? 2),
          'type': 'Mamba (S6)',
        }
      case 'memory':
        return {
          'num_banks': String(m.mem_num_banks ?? 3),
          'bank_size': String(m.mem_bank_size ?? 128),
          'd_key': String(m.mem_d_key ?? 64),
          'type': 'Differentiable content-addressed',
        }
      case 'regime':
        return {
          'num_regimes': String(m.num_regimes ?? 32),
          'gumbel_tau': String(m.gumbel_tau ?? 1.0),
          'type': 'Gumbel-Softmax discrete codes',
          'gradient': 'Detached (stop-grad)',
        }
      case 'gate':
        return {
          'gate_dim': `per-dim (d_model=${m.d_model ?? 4096})`,
          'activation': 'sigmoid',
          'init_bias': String(m.gate_init_bias ?? 1.0),
          'output': 'g in [0,1]^d',
        }
      case 'fusion':
        return {
          'formula': 'g*LN(Wh*h) + (1-g)*LN(Wz*z) + Wm*m + Wr*r_bar',
          'lm_head': 'Weight-tied with embedding',
          'vocab_size': String(m.vocab_size ?? 50257),
        }
      default:
        return {}
    }
  }

  // SVG layout constants
  const W = 580, H = 420
  const boxW = 110, boxH = 52
  const topY = 10, decoderY = 55, midY = 175, fuseY = 310, lmY = 375
  const cx = W / 2

  return (
    <Card>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold text-white">LOLM Architecture</h3>
        <span className="text-[9px] text-muted">Click any block to see config values</span>
      </div>
      <div className="relative overflow-x-auto">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full max-w-[580px] mx-auto"
          style={{ minWidth: 320 }}
        >
          <defs>
            <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="#475569" />
            </marker>
          </defs>

          {/* Token IDs */}
          <text x={cx} y={topY + 12} textAnchor="middle" fill="#94a3b8" fontSize={10} fontFamily="inherit">
            Token IDs
          </text>

          {/* Arrow: Tokens → Decoder */}
          <Arrow x1={cx} y1={topY + 18} x2={cx} y2={decoderY} />

          {/* Surface Decoder */}
          <ArchBox
            x={cx - 90} y={decoderY} w={180} h={boxH}
            color={ARCH_COLORS.surface}
            label="Surface Decoder"
            sublabel="16-layer Transformer + RoPE"
            onClick={() => setTooltip(tooltip?.key === 'surface' ? null : { key: 'surface', x: cx, y: decoderY + boxH })}
          />

          {/* h label */}
          <text x={cx} y={decoderY + boxH + 16} textAnchor="middle" fill="#60a5fa" fontSize={10} fontStyle="italic">
            h
          </text>

          {/* Arrows from decoder to 4 components */}
          {/* SSM */}
          <Arrow x1={cx - 50} y1={decoderY + boxH + 20} x2={55 + boxW / 2} y2={midY} />
          {/* Memory */}
          <Arrow x1={cx - 15} y1={decoderY + boxH + 20} x2={175 + boxW / 2 - 20} y2={midY} />
          {/* Regime */}
          <Arrow x1={cx + 15} y1={decoderY + boxH + 20} x2={305 + boxW / 2 - 20} y2={midY} />
          {/* Gate */}
          <Arrow x1={cx + 50} y1={decoderY + boxH + 20} x2={435 + boxW / 2 - 20} y2={midY} />

          {/* SSM */}
          <ArchBox
            x={20} y={midY} w={boxW} h={boxH}
            color={ARCH_COLORS.ssm}
            label="Latent SSM"
            sublabel="4-layer Mamba"
            onClick={() => setTooltip(tooltip?.key === 'ssm' ? null : { key: 'ssm', x: 75, y: midY + boxH })}
          />
          <text x={20 + boxW / 2} y={midY + boxH + 14} textAnchor="middle" fill="#34d399" fontSize={10} fontStyle="italic">z</text>

          {/* Memory */}
          <ArchBox
            x={155} y={midY} w={boxW} h={boxH}
            color={ARCH_COLORS.memory}
            label="Memory"
            sublabel="3 banks x 128 slots"
            onClick={() => setTooltip(tooltip?.key === 'memory' ? null : { key: 'memory', x: 210, y: midY + boxH })}
          />
          <text x={155 + boxW / 2} y={midY + boxH + 14} textAnchor="middle" fill="#fbbf24" fontSize={10} fontStyle="italic">m</text>

          {/* Regime */}
          <ArchBox
            x={290} y={midY} w={boxW} h={boxH}
            color={ARCH_COLORS.regime}
            label="Regime Layer"
            sublabel="32 Gumbel-Softmax"
            onClick={() => setTooltip(tooltip?.key === 'regime' ? null : { key: 'regime', x: 345, y: midY + boxH })}
          />
          <text x={290 + boxW / 2} y={midY + boxH + 14} textAnchor="middle" fill="#f87171" fontSize={10} fontStyle="italic">
            r (detach)
          </text>

          {/* Gate */}
          <ArchBox
            x={425} y={midY} w={boxW} h={boxH}
            color={ARCH_COLORS.gate}
            label="Gate"
            sublabel="per-dim g in [0,1]^d"
            onClick={() => setTooltip(tooltip?.key === 'gate' ? null : { key: 'gate', x: 480, y: midY + boxH })}
          />
          <text x={425 + boxW / 2} y={midY + boxH + 14} textAnchor="middle" fill="#c084fc" fontSize={10} fontStyle="italic">g</text>

          {/* Arrows from components to fusion */}
          <Arrow x1={20 + boxW / 2} y1={midY + boxH + 20} x2={cx - 40} y2={fuseY} />
          <Arrow x1={155 + boxW / 2} y1={midY + boxH + 20} x2={cx - 15} y2={fuseY} />
          <Arrow x1={290 + boxW / 2} y1={midY + boxH + 20} x2={cx + 15} y2={fuseY} />
          <Arrow x1={425 + boxW / 2} y1={midY + boxH + 20} x2={cx + 40} y2={fuseY} />

          {/* Fusion */}
          <ArchBox
            x={cx - 140} y={fuseY} w={280} h={boxH}
            color={ARCH_COLORS.fusion}
            label="Fusion"
            sublabel="g*LN(Wh*h) + (1-g)*LN(Wz*z) + Wm*m + Wr*r"
            onClick={() => setTooltip(tooltip?.key === 'fusion' ? null : { key: 'fusion', x: cx, y: fuseY + boxH })}
          />

          {/* Arrow to LM Head */}
          <Arrow x1={cx} y1={fuseY + boxH} x2={cx} y2={lmY} />

          {/* LM Head */}
          <rect x={cx - 70} y={lmY} width={140} height={32} rx={4}
            fill="#1e293b" stroke="#475569" strokeWidth={1} />
          <text x={cx} y={lmY + 20} textAnchor="middle" fill="#94a3b8" fontSize={10} fontFamily="inherit">
            LM Head (weight-tied)
          </text>
        </svg>

        {/* Tooltip overlay */}
        {tooltip && (
          <div
            className="absolute bg-surface border border-border rounded-lg shadow-xl p-3 z-10"
            style={{
              left: '50%',
              transform: 'translateX(-50%)',
              top: 16,
              minWidth: 240,
              maxWidth: 320,
            }}
          >
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs font-bold" style={{ color: ARCH_COLORS[tooltip.key as keyof typeof ARCH_COLORS]?.border ?? '#fff' }}>
                {ARCH_COLORS[tooltip.key as keyof typeof ARCH_COLORS]?.label ?? tooltip.key}
              </h4>
              <button onClick={() => setTooltip(null)} className="text-muted hover:text-white">
                <X size={12} />
              </button>
            </div>
            <div className="space-y-1">
              {Object.entries(getConfigValues(tooltip.key)).map(([k, v]) => (
                <div key={k} className="flex justify-between text-[10px]">
                  <span className="text-muted">{k}</span>
                  <span className="text-white font-mono">{v}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function ConfigField({ name, field, value, onChange }: {
  name: string
  field: { type: string; default: any; description: string }
  value: any
  onChange: (v: any) => void
}) {
  const [showDesc, setShowDesc] = useState(false)
  const displayValue = value ?? field.default

  return (
    <div className="flex items-start gap-3 py-2 border-b border-border/50 last:border-0">
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-white">{name}</label>
          <button onClick={() => setShowDesc(!showDesc)} className="text-muted hover:text-accent">
            <Info size={12} />
          </button>
        </div>
        {showDesc && (
          <p className="text-[10px] text-muted mt-1 leading-relaxed max-w-lg">{field.description}</p>
        )}
      </div>
      <div className="w-32">
        {field.type === 'bool' ? (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!displayValue} onChange={e => onChange(e.target.checked)}
              className="accent-accent" />
            <span className="text-xs text-muted">{displayValue ? 'ON' : 'OFF'}</span>
          </label>
        ) : field.type === 'float' ? (
          <input type="number" step="any" value={displayValue} onChange={e => onChange(parseFloat(e.target.value))}
            className="w-full bg-bg border border-border rounded px-2 py-1 text-xs text-white text-right" />
        ) : field.type === 'int' ? (
          <input type="number" value={displayValue} onChange={e => onChange(parseInt(e.target.value))}
            className="w-full bg-bg border border-border rounded px-2 py-1 text-xs text-white text-right" />
        ) : (
          <input type="text" value={displayValue} onChange={e => onChange(e.target.value)}
            className="w-full bg-bg border border-border rounded px-2 py-1 text-xs text-white" />
        )}
      </div>
    </div>
  )
}

function ConfigSection({ title, description, schema, config, path, onChange }: {
  title: string; description?: string; schema: Record<string, any>
  config: Record<string, any>; path: string[]; onChange: (path: string[], value: any) => void
}) {
  const [open, setOpen] = useState(true)

  const fields = Object.entries(schema).filter(([k]) => !k.startsWith('_'))
  const subSections = fields.filter(([, v]) => typeof v === 'object' && !('type' in v))
  const directFields = fields.filter(([, v]) => typeof v === 'object' && 'type' in v)

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 bg-surface-2 hover:bg-surface text-xs font-semibold text-white">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {title}
        {description && <span className="text-muted font-normal ml-2">— {description}</span>}
      </button>
      {open && (
        <div className="px-4 py-2">
          {directFields.map(([key, field]) => (
            <ConfigField
              key={key}
              name={key}
              field={field as any}
              value={path.reduce((obj, k) => obj?.[k], config)?.[key]}
              onChange={(v) => onChange([...path, key], v)}
            />
          ))}
          {subSections.map(([key, sub]) => (
            <div key={key} className="mt-3">
              <ConfigSection
                title={key.toUpperCase()}
                description={(sub as any)._description}
                schema={sub}
                config={config}
                path={[...path, key]}
                onChange={onChange}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ConfigPanel() {
  const configs = useStore(s => s.configs)
  const setConfigs = useStore(s => s.setConfigs)
  const schema = useStore(s => s.schema)
  const setSchema = useStore(s => s.setSchema)
  const activeConfig = useStore(s => s.activeConfig)
  const setActiveConfig = useStore(s => s.setActiveConfig)
  const [selectedFile, setSelectedFile] = useState('')
  const [saving, setSaving] = useState(false)
  const [modified, setModified] = useState(false)

  useEffect(() => {
    api.get('/configs').then(r => setConfigs(r.data.configs || []))
    api.get('/configs/schema').then(r => setSchema(r.data))
  }, [])

  const loadConfig = async (name: string) => {
    setSelectedFile(name)
    try {
      const res = await api.get(`/configs/${name}`)
      setActiveConfig(res.data.config)
      setModified(false)
    } catch {}
  }

  const handleChange = (path: string[], value: any) => {
    if (!activeConfig) return
    const next = JSON.parse(JSON.stringify(activeConfig))
    let obj = next
    for (let i = 0; i < path.length - 1; i++) {
      if (!obj[path[i]]) obj[path[i]] = {}
      obj = obj[path[i]]
    }
    obj[path[path.length - 1]] = value
    setActiveConfig(next)
    setModified(true)
  }

  const saveConfig = async () => {
    if (!selectedFile || !activeConfig) return
    setSaving(true)
    try {
      await api.put(`/configs/${selectedFile}`, activeConfig)
      setModified(false)
    } catch {}
    setSaving(false)
  }

  // Estimate parameter count
  const estimateParams = () => {
    if (!activeConfig?.model) return '—'
    const m = activeConfig.model
    const d = m.d_model || 4096
    const L = m.n_layers || 32
    const dff = m.d_ff || 8192
    const V = m.vocab_size || 50257
    const embed = V * d
    const perBlock = 4 * d * d + 2 * d * dff  // attn + ff
    const total = embed + L * perBlock
    return `~${(total / 1e9).toFixed(1)}B`
  }

  return (
    <div className="space-y-4">
      {/* Architecture Diagram */}
      <ArchitectureDiagram config={activeConfig} />

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Architecture Config</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">Est. params: <span className="text-accent font-bold">{estimateParams()}</span></span>
          <select value={selectedFile} onChange={e => loadConfig(e.target.value)}
            className="bg-bg border border-border rounded px-2 py-1.5 text-xs text-white">
            <option value="">Select config...</option>
            {configs.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          {modified && (
            <button onClick={saveConfig} disabled={saving}
              className="flex items-center gap-2 px-3 py-1.5 bg-accent text-white text-xs rounded hover:bg-accent-2 disabled:opacity-50">
              <Save size={14} /> {saving ? 'Saving...' : 'Save'}
            </button>
          )}
        </div>
      </div>

      {!activeConfig || !schema ? (
        <Card>
          <p className="text-muted text-sm text-center py-8">
            Select a config file to edit. Every parameter includes a description from the LOLM paper.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {Object.entries(schema).map(([section, sectionSchema]) => (
            <ConfigSection
              key={section}
              title={section.toUpperCase()}
              description={(sectionSchema as any)._description}
              schema={sectionSchema}
              config={activeConfig}
              path={[section]}
              onChange={handleChange}
            />
          ))}
        </div>
      )}
    </div>
  )
}
