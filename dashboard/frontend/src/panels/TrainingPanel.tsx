import { useEffect, useRef, useState, useCallback } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Play, Square, RefreshCw, Wifi, WifiOff, AlertCircle, Zap, Star } from 'lucide-react'
import Card from '../components/Card'
import Stat from '../components/Stat'
import StatusBadge from '../components/StatusBadge'
import { useStore } from '../store'
import { useWebSocket } from '../hooks/useWebSocket'
import api from '../api'

const LOSS_COLORS: Record<string, string> = {
  loss: '#a78bfa',
  loss_tok: '#34d399',
  loss_future: '#fbbf24',
  loss_changepoint: '#f87171',
  loss_regime: '#60a5fa',
  loss_competitive: '#22d3ee',
  loss_mem: '#f472b6',
}

export default function TrainingPanel() {
  const liveMetrics = useStore(s => s.liveMetrics)
  const logLines = useStore(s => s.logLines)
  const addLogLine = useStore(s => s.addLogLine)
  const clearLogs = useStore(s => s.clearLogs)
  const trainingStatus = useStore(s => s.trainingStatus)
  const setTrainingStatus = useStore(s => s.setTrainingStatus)
  const logEndRef = useRef<HTMLDivElement>(null)
  const [visibleLosses, setVisibleLosses] = useState<Set<string>>(new Set(['loss', 'loss_tok', 'loss_future']))
  const [launching, setLaunching] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [aiAnalysis, setAiAnalysis] = useState<{ analysis: string; step: number; timestamp: string } | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [modelInfo, setModelInfo] = useState<Record<string, any>>({})

  // Fetch model info once (from beginning of log)
  useEffect(() => {
    api.get('/training/model-info', { params: { tpu_name: 'lolm-7b' } })
      .then(r => setModelInfo(r.data || {}))
      .catch(() => {})
  }, [])

  // Always try to connect WebSocket to lolm-7b
  useWebSocket('lolm-7b')

  // Poll training status every 10s AND load full log
  const checkStatus = useCallback(async () => {
    try {
      const res = await api.get('/training/status', { params: { tpu_name: 'lolm-7b' } })
      setTrainingStatus(res.data)

      // Fetch more lines on first load (to get model info), less on subsequent polls
      const numLines = logLines.length === 0 ? 200 : 50
      const logRes = await api.get('/training/log/recent', { params: { tpu_name: 'lolm-7b', lines: numLines } })
      if (logRes.data.lines?.length > 0) {
        clearLogs()
        logRes.data.lines.forEach((line: string) => addLogLine(line))
      }
    } catch {}
  }, [setTrainingStatus, addLogLine, clearLogs])

  useEffect(() => {
    checkStatus()
    const interval = setInterval(checkStatus, 10000)
    return () => clearInterval(interval)
  }, [checkStatus])

  // Auto-scroll log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logLines])

  const lastMetric = liveMetrics[liveMetrics.length - 1]
  const isRunning = trainingStatus?.running

  // Load latest AI analysis on mount
  useEffect(() => {
    api.get('/analysis/latest').then(r => {
      if (r.data.analysis) setAiAnalysis(r.data.analysis)
    }).catch(() => {})
  }, [])

  // Auto-run AI analysis every 5 min when training
  useEffect(() => {
    if (!isRunning || !lastMetric?.step) return
    const interval = setInterval(async () => {
      try {
        setAnalyzing(true)
        const res = await api.post('/analysis/run', null, {
          params: {
            step: lastMetric.step, loss: lastMetric.loss, loss_tok: lastMetric.loss_tok,
            ppl: lastMetric.ppl, gate: lastMetric.gate, regimes: lastMetric.regimes,
            cpc_future: lastMetric.loss_future, steps_per_sec: lastMetric.steps_per_sec,
          }
        })
        if (res.data.analysis) setAiAnalysis(res.data.analysis)
      } catch {} finally { setAnalyzing(false) }
    }, 300000) // 5 min
    return () => clearInterval(interval)
  }, [isRunning, lastMetric])

  // Parse log for model info + phase tracking with ETAs
  const logInfo = (() => {
    const info: Record<string, string> = {}
    const phases: { name: string; time?: string; done: boolean }[] = []
    let phaseIdx = 0
    let lastStepTime = 0
    let firstStepTime = 0
    let lastStep = 0
    let maxSteps = 50000

    for (const line of logLines) {
      // Model info
      if (line.includes('total:')) {
        const m = line.match(/([\d,]+)/)
        if (m) info.params = (parseInt(m[1].replace(/,/g, '')) / 1e9).toFixed(1) + 'B'
      }
      if (line.includes('Global batch:')) {
        const m = line.match(/Global batch:\s*(\d+)/)
        if (m) info.batch = m[1]
      }
      if (line.includes('Chips:')) {
        const m = line.match(/Chips:\s*(\d+)/)
        if (m) info.chips = m[1]
      }
      if (line.includes('FSDP wrapping complete')) info.fsdp = '✓'
      if (line.includes('Streaming from:') || line.includes('fineweb') || line.includes('parquet')) {
        if (line.includes('fineweb')) info.dataset = 'FineWeb-Edu'
        else if (line.includes('TinyStories')) info.dataset = 'TinyStories'
        else if (line.includes('parquet')) info.dataset = 'Local Parquet'
      }
      if (line.includes('Steps:')) {
        const m = line.match(/→\s*(\d+)/)
        if (m) maxSteps = parseInt(m[1])
      }

      // Phase detection
      if (line.includes('Pre-download:') || line.includes('parquet')) {
        if (phaseIdx < 1) phaseIdx = 1
        info.phase = 'Downloading data'
        info.phaseEta = '~2-10 min'
      }
      if (line.includes('PJRT') || line.includes('pjrt_api')) {
        if (phaseIdx < 2) phaseIdx = 2
        info.phase = 'PJRT init'
        info.phaseEta = '~30 sec'
      }
      if (line.includes('Parameters:') || line.includes('total:')) {
        if (phaseIdx < 3) phaseIdx = 3
        info.phase = 'Building model'
        info.phaseEta = '~1 min'
      }
      if (line.includes('FSDP wrapping complete') || line.includes('FSDP:')) {
        if (phaseIdx < 4) phaseIdx = 4
        info.phase = 'FSDP wrapping'
        info.phaseEta = '~30 sec'
      }
      if (line.includes('Loading data') || line.includes('Streaming from:')) {
        if (phaseIdx < 5) phaseIdx = 5
        info.phase = 'Loading data'
        info.phaseEta = '~1 min'
      }
      if (line.includes('Starting LOLM Pod Training')) {
        if (phaseIdx < 6) phaseIdx = 6
        info.phase = 'XLA compiling'
        info.phaseEta = '~30-40 min'
      }
      if (line.startsWith('step')) {
        if (phaseIdx < 7) {
          phaseIdx = 7
          firstStepTime = Date.now() / 1000
        }
        info.phase = 'Training'
        const sm = line.match(/step\s+(\d+)/)
        if (sm) lastStep = parseInt(sm[1])
        const sps = line.match(/([\d.]+)\s+steps\/s/)
        if (sps) {
          const stepsPerSec = parseFloat(sps[1])
          const remaining = maxSteps - lastStep
          const secsLeft = remaining / stepsPerSec
          if (secsLeft < 3600) {
            info.phaseEta = `~${Math.ceil(secsLeft / 60)} min left`
          } else if (secsLeft < 86400) {
            info.phaseEta = `~${(secsLeft / 3600).toFixed(1)} hrs left`
          } else {
            info.phaseEta = `~${(secsLeft / 86400).toFixed(1)} days left`
          }
        }
      }
      if (line.includes('RESOURCE_EXHAUSTED')) {
        info.phase = 'OOM Error'
        info.phaseEta = 'Auto-retrying...'
      }
      if (line.includes('retrying') || line.includes('Retry')) {
        info.phase = 'Auto-retrying'
        info.phaseEta = '~2 min'
      }
    }

    // Build phase timeline
    const PHASES = ['Init', 'Download', 'PJRT', 'Model', 'FSDP', 'Data', 'XLA Compile', 'Training']
    info.phaseTimeline = JSON.stringify(PHASES.map((name, i) => ({
      name,
      done: i < phaseIdx,
      active: i === phaseIdx,
    })))

    info.maxSteps = String(maxSteps)

    return info
  })()

  const handleLaunch = async () => {
    setLaunching(true)
    clearLogs()
    addLogLine('[DASHBOARD] Launching training on lolm-7b...')
    addLogLine('[DASHBOARD] SSHing to 4 workers, pulling code, cleaning devices...')
    addLogLine('[DASHBOARD] This takes ~2 minutes. Please wait...')
    try {
      const res = await api.post('/training/launch', null, {
        params: { tpu_name: 'lolm-7b', config: 'configs/scale/7b_lolm_pod.yaml' },
        timeout: 300000, // 5 min timeout for SSH operations
      })
      if (res.data.success) {
        addLogLine(`[DASHBOARD] ✓ Training launched on ${res.data.job?.ips?.length || 4} workers`)
        addLogLine(`[DASHBOARD] Config: ${res.data.job?.config}`)
        addLogLine(`[DASHBOARD] Waiting for XLA compilation (~30-40 min)...`)
        setTrainingStatus({ running: true, log_tail: [], job: res.data.job })
      } else {
        addLogLine(`[DASHBOARD] ✗ Launch failed: ${res.data.error}`)
      }
    } catch (e: any) {
      addLogLine(`[DASHBOARD] ✗ Launch error: ${e.message}`)
    }
    setLaunching(false)
  }

  const handleStop = async () => {
    addLogLine('[DASHBOARD] Stopping training...')
    try {
      await api.post('/training/stop', null, { params: { tpu_name: 'lolm-7b' } })
      addLogLine('[DASHBOARD] ✓ Training stopped')
    } catch (e: any) {
      addLogLine(`[DASHBOARD] ✗ Stop error: ${e.message}`)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await api.get('/training/log/recent', { params: { tpu_name: 'lolm-7b', lines: 50 } })
      if (res.data.lines?.length > 0) {
        clearLogs()
        res.data.lines.forEach((line: string) => addLogLine(line))
      }
    } catch {}
    await checkStatus()
    setRefreshing(false)
  }

  const toggleLoss = (key: string) => {
    const next = new Set(visibleLosses)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setVisibleLosses(next)
  }

  return (
    <div className="space-y-3">
      {/* Header — always visible */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 bg-surface border border-border rounded-lg p-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm sm:text-lg font-bold">Training Monitor</h2>
          <StatusBadge status={isRunning ? 'RUNNING' : 'STOPPED'} />
        </div>
        <div className="flex gap-2 w-full sm:w-auto">
          {!isRunning ? (
            <button
              onClick={handleLaunch}
              disabled={launching}
              className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 bg-success/20 text-success text-xs font-semibold rounded hover:bg-success/30 disabled:opacity-50"
            >
              <Play size={14} /> {launching ? 'Launching... (2min)' : 'Launch Training'}
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 bg-danger/20 text-danger text-xs font-semibold rounded hover:bg-danger/30"
            >
              <Square size={14} /> Stop Training
            </button>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 px-3 py-2 bg-surface-2 text-muted text-xs rounded hover:text-white"
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Phase Timeline + ETA */}
      {isRunning && logInfo.phase && (
        <div className="bg-surface border border-border rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-success animate-pulse" />
              <span className="text-xs font-semibold text-white">{logInfo.phase}</span>
            </div>
            {logInfo.phaseEta && (
              <span className="text-xs text-warning font-mono">{logInfo.phaseEta}</span>
            )}
          </div>
          {/* Phase progress bar */}
          {(() => {
            try {
              const phases: { name: string; done: boolean; active: boolean }[] = JSON.parse(logInfo.phaseTimeline || '[]')
              return (
                <div className="flex gap-0.5">
                  {phases.map((p, i) => (
                    <div key={i} className="flex-1 flex flex-col items-center gap-1">
                      <div className={`w-full h-1.5 rounded-full ${
                        p.done ? 'bg-success' : p.active ? 'bg-warning animate-pulse' : 'bg-border'
                      }`} />
                      <span className={`text-[8px] ${
                        p.done ? 'text-success' : p.active ? 'text-warning' : 'text-muted/50'
                      }`}>{p.name}</span>
                    </div>
                  ))}
                </div>
              )
            } catch { return null }
          })()}
          {/* Training progress if we have steps */}
          {lastMetric?.step != null && (
            <div className="mt-2">
              <div className="flex justify-between text-[10px] text-muted mb-1">
                <span>Step {lastMetric.step.toLocaleString()}</span>
                <span>{parseInt(logInfo.maxSteps || '50000').toLocaleString()} total</span>
              </div>
              <div className="w-full bg-border rounded-full h-2">
                <div
                  className="bg-accent h-2 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, (lastMetric.step / parseInt(logInfo.maxSteps || '50000')) * 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Key Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat label="Step" value={lastMetric?.step ?? '0'} sub="/ 50000" />
        <Stat label="Loss" value={lastMetric?.loss?.toFixed(4) ?? (logInfo.phase || '—')} color={logInfo.phase === 'OOM Error' ? 'text-danger' : 'text-accent'} />
        <Stat label="Params" value={modelInfo.params || logInfo.params || '—'} sub={modelInfo.fsdp !== undefined ? (modelInfo.fsdp ? 'FSDP ✓' : 'Single device') : ''} color="text-white" />
        <Stat label="Gate Mean" value={lastMetric?.gate?.toFixed(3) ?? '—'} sub="0=latent 1=surface" />
        <Stat label="Chips" value={modelInfo.chips || logInfo.chips || '—'} sub={modelInfo.batch ? `batch ${modelInfo.batch}` : ''} />
        <Stat label="Dataset" value={modelInfo.dataset || logInfo.dataset || '—'} sub={lastMetric?.lr ? `lr ${lastMetric.lr.toExponential(1)}` : ''} color="text-white" />
      </div>

      {/* Main Loss Chart — total, token, future */}
      <Card title="Main Loss (total / token / CPC future)">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={liveMetrics}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="step" stroke="#64748b" fontSize={10} />
            <YAxis stroke="#64748b" fontSize={10} />
            <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #1e293b', fontSize: 11 }} />
            <Line type="monotone" dataKey="loss" stroke="#a78bfa" dot={false} strokeWidth={2} isAnimationActive={false} name="total" />
            <Line type="monotone" dataKey="loss_tok" stroke="#34d399" dot={false} strokeWidth={1.5} isAnimationActive={false} name="token CE" />
            <Line type="monotone" dataKey="loss_future" stroke="#fbbf24" dot={false} strokeWidth={1.5} isAnimationActive={false} name="CPC future" />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      {/* Auxiliary Loss Chart — on their own scale so they're readable */}
      <Card title="Auxiliary Losses (regime / competitive / changepoint / memory / gate)">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={liveMetrics}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="step" stroke="#64748b" fontSize={10} />
            <YAxis stroke="#64748b" fontSize={10} />
            <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #1e293b', fontSize: 11 }} />
            <Line type="monotone" dataKey="loss_regime" stroke="#60a5fa" dot={false} strokeWidth={1.5} isAnimationActive={false} name="regime" />
            <Line type="monotone" dataKey="loss_competitive" stroke="#22d3ee" dot={false} strokeWidth={1.5} isAnimationActive={false} name="competitive" />
            <Line type="monotone" dataKey="loss_changepoint" stroke="#f87171" dot={false} strokeWidth={1.5} isAnimationActive={false} name="changepoint" />
            <Line type="monotone" dataKey="loss_mem" stroke="#f472b6" dot={false} strokeWidth={1.5} isAnimationActive={false} name="memory" />
            <Line type="monotone" dataKey="loss_manifest" stroke="#94a3b8" dot={false} strokeWidth={1.5} isAnimationActive={false} name="gate reg" />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      {/* Live Log */}
      <Card title="Training Log">
        <div className="log-terminal bg-bg rounded p-3 h-48 sm:h-64 overflow-y-auto font-mono text-[11px]">
          {logLines.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted gap-2">
              <WifiOff size={20} />
              <p>No log data yet.</p>
              <p className="text-[10px]">Click Refresh to load latest log, or Launch Training to start.</p>
            </div>
          ) : (
            logLines.map((line, i) => {
              let cls = 'log-info'
              if (line.startsWith('step')) cls = 'log-step'
              else if (line.startsWith('[DASHBOARD]')) cls = line.includes('✗') ? 'log-error' : 'text-accent'
              else if (line.includes('Error') || line.includes('RESOURCE_EXHAUSTED')) cls = 'log-error'
              else if (line.includes('WARNING') || line.includes('FSDP')) cls = 'log-warning'
              else if (line.includes('Starting') || line.includes('complete')) cls = 'text-success'
              return <div key={i} className={cls}>{line}</div>
            })
          )}
          <div ref={logEndRef} />
        </div>
      </Card>

      {/* AI Analysis */}
      <Card title="AI Training Analysis">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap size={14} className="text-accent" />
            <span className="text-[10px] text-muted">
              {aiAnalysis ? `Last analysis: step ${aiAnalysis.step} • ${new Date(aiAnalysis.timestamp).toLocaleTimeString()}` : 'No analysis yet'}
            </span>
          </div>
          <button
            onClick={async () => {
              if (!lastMetric?.step) return
              setAnalyzing(true)
              try {
                const res = await api.post('/analysis/run', null, {
                  params: {
                    step: lastMetric.step, loss: lastMetric.loss, loss_tok: lastMetric.loss_tok,
                    ppl: lastMetric.ppl, gate: lastMetric.gate, regimes: lastMetric.regimes,
                    cpc_future: lastMetric.loss_future, steps_per_sec: lastMetric.steps_per_sec,
                  }
                })
                if (res.data.analysis) setAiAnalysis(res.data.analysis)
              } catch {} finally { setAnalyzing(false) }
            }}
            disabled={analyzing || !lastMetric?.step}
            className="flex items-center gap-1.5 px-2 py-1 bg-accent/20 text-accent text-[10px] rounded hover:bg-accent/30 disabled:opacity-50"
          >
            <Star size={10} className={analyzing ? 'animate-spin' : ''} />
            {analyzing ? 'Analyzing...' : 'Analyze Now'}
          </button>
        </div>
        {aiAnalysis?.analysis ? (
          <div className="bg-bg rounded p-3 text-[11px] text-gray-300 leading-relaxed whitespace-pre-wrap">
            {aiAnalysis.analysis}
          </div>
        ) : (
          <p className="text-[11px] text-muted text-center py-4">
            {lastMetric?.step ? 'Click "Analyze Now" to get AI insights on your training run.' : 'Waiting for training data...'}
          </p>
        )}
      </Card>

      {/* Live Comparison vs Baselines */}
      {lastMetric?.loss != null && (
        <Card title="How LOLM Compares">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="bg-surface-2 rounded-lg p-3">
              <p className="text-[10px] text-muted">LOLM 1B (current, step {lastMetric.step})</p>
              <p className="text-xl font-black text-accent">{lastMetric.loss.toFixed(2)}</p>
              <p className="text-[10px] text-muted">token loss</p>
            </div>
            <div className="bg-surface-2 rounded-lg p-3">
              <p className="text-[10px] text-muted">7B Baseline (step ~15K)</p>
              <p className="text-xl font-black text-muted">5.10</p>
              <p className="text-[10px] text-muted">token loss (mature, 15K steps in)</p>
            </div>
            <div className="bg-surface-2 rounded-lg p-3">
              <p className="text-[10px] text-muted">LOLM-304M (paper, step 20K)</p>
              <p className="text-xl font-black text-success">3.57</p>
              <p className="text-[10px] text-muted">token loss on FineWeb-Edu</p>
            </div>
            <div className="bg-surface-2 rounded-lg p-3">
              <p className="text-[10px] text-muted">LOLM-1.57B (paper, step 20K)</p>
              <p className="text-xl font-black text-success">3.50</p>
              <p className="text-[10px] text-muted">token loss on FineWeb-Edu</p>
            </div>
          </div>
          <p className="text-[10px] text-muted mt-3">
            Current run is early training — loss will continue dropping. The 304M model took ~5K steps to reach loss &lt;10.
            At step {lastMetric.step}, the model is in warmup ({(lastMetric.lr ?? 0).toExponential(1)} LR).
            Loss curves improve dramatically after warmup ends at step 2000.
          </p>
          <div className="mt-3 pt-3 border-t border-border/50">
            <p className="text-[10px] text-muted mb-2">Reference PPL at scale (WikiText-103, fully trained):</p>
            <div className="flex flex-wrap gap-2 text-[10px]">
              <span className="bg-bg px-2 py-1 rounded">GPT-2 Small (124M): <span className="text-white">37.5</span></span>
              <span className="bg-bg px-2 py-1 rounded">GPT-2 Medium (355M): <span className="text-white">26.4</span></span>
              <span className="bg-bg px-2 py-1 rounded">Pythia-410M: <span className="text-white">142.9</span></span>
              <span className="bg-bg px-2 py-1 rounded">LOLM-304M: <span className="text-accent">68.4</span></span>
              <span className="bg-bg px-2 py-1 rounded">Pythia-1B: <span className="text-white">54.0</span></span>
              <span className="bg-bg px-2 py-1 rounded">Mamba-1.4B: <span className="text-white">16.1</span></span>
              <span className="bg-bg px-2 py-1 rounded">LLaMA-7B: <span className="text-white">12.6</span></span>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
