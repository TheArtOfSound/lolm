import { useState, useEffect } from 'react'
import { BarChart3, Play, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import api from '../api'

interface EvalResult {
  id: string
  checkpoint: string
  benchmarks: string[]
  status: string
  started_at: string
  results?: Record<string, any>
  raw_output?: string
}

interface AvailableCheckpoint {
  path: string
  step: number
  size_gb: number
  source: string
}

export default function EvalPanel() {
  const [checkpoints, setCheckpoints] = useState<AvailableCheckpoint[]>([])
  const [results, setResults] = useState<EvalResult[]>([])
  const [selectedCkpt, setSelectedCkpt] = useState('')
  const [benchmarks, setBenchmarks] = useState(['wikitext-103'])
  const [running, setRunning] = useState(false)
  const [liveOutput, setLiveOutput] = useState('')

  useEffect(() => {
    loadCheckpoints()
    loadResults()
  }, [])

  async function loadCheckpoints() {
    try {
      const res = await api.get('/eval/available-checkpoints')
      setCheckpoints(res.data.checkpoints || [])
      if (res.data.checkpoints?.length > 0 && !selectedCkpt) {
        setSelectedCkpt(res.data.checkpoints[0].path)
      }
    } catch {}
  }

  async function loadResults() {
    try {
      const res = await api.get('/eval/results')
      setResults(res.data.results || [])
    } catch {}
  }

  async function runEval() {
    if (!selectedCkpt) return
    setRunning(true)
    setLiveOutput('Starting evaluation...\n')
    try {
      const res = await api.post('/eval/run', null, {
        params: {
          checkpoint: selectedCkpt,
          benchmarks: benchmarks.join(','),
        }
      })
      setLiveOutput(res.data.raw_output || JSON.stringify(res.data, null, 2))
      loadResults()
    } catch (e: any) {
      setLiveOutput('Error: ' + (e.message || 'Unknown error'))
    }
    setRunning(false)
  }

  async function runEnterprise() {
    setRunning(true)
    setLiveOutput('Running enterprise report...\n')
    try {
      const res = await api.post('/eval/enterprise-report')
      setLiveOutput(res.data.report || res.data.error || 'No output')
    } catch (e: any) {
      setLiveOutput('Error: ' + (e.message || 'Unknown error'))
    }
    setRunning(false)
  }

  const allBenchmarks = ['wikitext-103', 'hellaswag', 'lambada']

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <BarChart3 size={20} className="text-accent" /> Evaluate Model
          </h2>
          <p className="text-xs text-muted mt-1">Run benchmarks on any checkpoint</p>
        </div>
        <button onClick={() => { loadCheckpoints(); loadResults() }}
          className="text-muted hover:text-white transition-colors">
          <RefreshCw size={16} />
        </button>
      </div>

      {/* Checkpoint Selector */}
      <div className="bg-surface border border-border rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-bold text-white">Select Checkpoint</h3>
        <select value={selectedCkpt} onChange={e => setSelectedCkpt(e.target.value)}
          className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white">
          <option value="">Select a checkpoint...</option>
          {checkpoints.map(ckpt => (
            <option key={ckpt.path} value={ckpt.path}>
              Step {ckpt.step.toLocaleString()} — {ckpt.size_gb}GB ({ckpt.source})
            </option>
          ))}
        </select>
      </div>

      {/* Benchmark Selector */}
      <div className="bg-surface border border-border rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-bold text-white">Benchmarks</h3>
        <div className="flex flex-wrap gap-2">
          {allBenchmarks.map(b => (
            <label key={b} className="flex items-center gap-2 text-xs text-muted">
              <input type="checkbox" checked={benchmarks.includes(b)}
                onChange={e => {
                  if (e.target.checked) setBenchmarks([...benchmarks, b])
                  else setBenchmarks(benchmarks.filter(x => x !== b))
                }}
                className="accent-accent" />
              {b}
            </label>
          ))}
        </div>

        <div className="flex gap-2 pt-2">
          <button onClick={runEval} disabled={running || !selectedCkpt}
            className="px-4 py-2 bg-accent text-white rounded text-xs font-bold disabled:opacity-50 flex items-center gap-2">
            <Play size={14} /> {running ? 'Running...' : 'Run Evaluation'}
          </button>
          <button onClick={runEnterprise} disabled={running}
            className="px-4 py-2 bg-emerald-600 text-white rounded text-xs font-bold disabled:opacity-50 flex items-center gap-2">
            <BarChart3 size={14} /> Enterprise Report
          </button>
        </div>
      </div>

      {/* Live Output */}
      {liveOutput && (
        <div className="bg-surface border border-border rounded-lg p-4">
          <h3 className="text-sm font-bold text-white mb-2">Output</h3>
          <pre className="text-[10px] text-muted font-mono whitespace-pre-wrap max-h-60 overflow-y-auto bg-bg p-3 rounded">
            {liveOutput}
          </pre>
        </div>
      )}

      {/* Results History */}
      <div className="bg-surface border border-border rounded-lg p-4">
        <h3 className="text-sm font-bold text-white mb-3">Evaluation History</h3>
        {results.length === 0 ? (
          <p className="text-xs text-muted">No evaluations yet. Run one above.</p>
        ) : (
          <div className="space-y-2">
            {results.slice().reverse().map(r => (
              <div key={r.id} className="bg-bg border border-border rounded p-3 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    {r.status === 'completed' ? <CheckCircle size={14} className="text-emerald-400" /> : <XCircle size={14} className="text-red-400" />}
                    <span className="text-xs text-white font-bold">{r.benchmarks?.join(', ')}</span>
                  </div>
                  <p className="text-[10px] text-muted mt-0.5">
                    {r.checkpoint?.split('/').pop()} — {r.started_at?.split('T')[0]}
                  </p>
                </div>
                {r.results && (
                  <div className="text-right">
                    {Object.entries(r.results).map(([k, v]) => (
                      <p key={k} className="text-[10px] text-muted">{k}: {typeof v === 'number' ? v.toFixed(2) : String(v)}</p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
