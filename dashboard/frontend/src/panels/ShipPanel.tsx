import { useState, useEffect } from 'react'
import { Upload, ExternalLink, RefreshCw, CheckCircle, FileText } from 'lucide-react'
import api from '../api'

interface PublishedModel {
  model_name: string
  checkpoint: string
  published_at: string
  success: boolean
  url: string
}

export default function ShipPanel() {
  const [modelName, setModelName] = useState('qira-llc/lolm-0.87b-fineweb-v1')
  const [params, setParams] = useState('865M')
  const [dataset, setDataset] = useState('FineWeb-Edu')
  const [steps, setSteps] = useState('50000')
  const [tokenLoss, setTokenLoss] = useState('5.32')
  const [gateMean, setGateMean] = useState('0.81')
  const [modelCard, setModelCard] = useState('')
  const [published, setPublished] = useState<PublishedModel[]>([])
  const [publishing, setPublishing] = useState(false)
  const [status, setStatus] = useState('')

  useEffect(() => {
    loadPublished()
  }, [])

  async function loadPublished() {
    try {
      const res = await api.get('/publish/models')
      setPublished(res.data.models || [])
    } catch {}
  }

  async function generateCard() {
    try {
      const res = await api.post('/publish/generate-card', null, {
        params: { model_name: modelName, params, dataset, steps, token_loss: tokenLoss, gate_mean: gateMean }
      })
      setModelCard(res.data.card || '')
    } catch (e: any) {
      setStatus('Error generating card: ' + e.message)
    }
  }

  async function publishModel() {
    setPublishing(true)
    setStatus('Publishing to HuggingFace...')
    try {
      const res = await api.post('/publish/push', null, {
        params: { model_name: modelName, params, dataset, steps, token_loss: tokenLoss, gate_mean: gateMean }
      })
      if (res.data.success) {
        setStatus('Published successfully!')
        loadPublished()
      } else {
        setStatus('Failed: ' + (res.data.error || res.data.output || 'Unknown error'))
      }
    } catch (e: any) {
      setStatus('Error: ' + e.message)
    }
    setPublishing(false)
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Upload size={20} className="text-accent" /> Ship Model
          </h2>
          <p className="text-xs text-muted mt-1">Publish trained LOLM checkpoints to HuggingFace Hub</p>
        </div>
      </div>

      {/* Model Configuration */}
      <div className="bg-surface border border-border rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-bold text-white">Model Details</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-muted block mb-1">Model Name (HF repo)</label>
            <input value={modelName} onChange={e => setModelName(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="text-[10px] text-muted block mb-1">Parameters</label>
            <input value={params} onChange={e => setParams(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="text-[10px] text-muted block mb-1">Dataset</label>
            <input value={dataset} onChange={e => setDataset(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="text-[10px] text-muted block mb-1">Training Steps</label>
            <input value={steps} onChange={e => setSteps(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="text-[10px] text-muted block mb-1">Token Loss</label>
            <input value={tokenLoss} onChange={e => setTokenLoss(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="text-[10px] text-muted block mb-1">Gate Mean</label>
            <input value={gateMean} onChange={e => setGateMean(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white" />
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <button onClick={generateCard}
            className="px-4 py-2 bg-surface-2 text-white rounded text-xs font-bold flex items-center gap-2 hover:bg-surface-2/80">
            <FileText size={14} /> Preview Model Card
          </button>
          <button onClick={publishModel} disabled={publishing}
            className="px-4 py-2 bg-accent text-white rounded text-xs font-bold disabled:opacity-50 flex items-center gap-2">
            <Upload size={14} /> {publishing ? 'Publishing...' : 'Publish to HuggingFace'}
          </button>
        </div>

        {status && (
          <p className={`text-xs ${status.includes('success') ? 'text-emerald-400' : 'text-amber-400'}`}>{status}</p>
        )}
      </div>

      {/* Model Card Preview */}
      {modelCard && (
        <div className="bg-surface border border-border rounded-lg p-4">
          <h3 className="text-sm font-bold text-white mb-2">Model Card Preview</h3>
          <pre className="text-[10px] text-muted font-mono whitespace-pre-wrap max-h-60 overflow-y-auto bg-bg p-3 rounded">
            {modelCard}
          </pre>
        </div>
      )}

      {/* Published Models */}
      <div className="bg-surface border border-border rounded-lg p-4">
        <h3 className="text-sm font-bold text-white mb-3 flex items-center justify-between">
          Published Models
          <button onClick={loadPublished} className="text-muted hover:text-white">
            <RefreshCw size={14} />
          </button>
        </h3>
        {published.length === 0 ? (
          <p className="text-xs text-muted">No models published yet.</p>
        ) : (
          <div className="space-y-2">
            {published.map((m, i) => (
              <div key={i} className="bg-bg border border-border rounded p-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CheckCircle size={14} className="text-emerald-400" />
                  <div>
                    <span className="text-xs text-white font-bold">{m.model_name}</span>
                    <p className="text-[10px] text-muted">{m.published_at?.split('T')[0]}</p>
                  </div>
                </div>
                <a href={m.url} target="_blank" rel="noopener noreferrer"
                  className="text-accent text-xs flex items-center gap-1 hover:underline">
                  View <ExternalLink size={12} />
                </a>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
