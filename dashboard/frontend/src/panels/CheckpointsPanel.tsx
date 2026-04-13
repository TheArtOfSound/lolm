import { useEffect, useState } from 'react'
import { Save, Download, Trash2, Play, RefreshCw, HardDrive } from 'lucide-react'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import api from '../api'

interface Checkpoint {
  name: string
  path: string
  run: string
  step: number
  size_gb: number
  timestamp: number
  tpu: string
}

export default function CheckpointsPanel() {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([])
  const [loading, setLoading] = useState(false)
  const [resuming, setResuming] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<string | null>(null)

  const fetchCheckpoints = async () => {
    setLoading(true)
    try {
      const res = await api.get('/checkpoints', { params: { tpu_name: 'lolm-7b' } })
      setCheckpoints(res.data.checkpoints || [])
    } catch {}
    setLoading(false)
  }

  useEffect(() => { fetchCheckpoints() }, [])
  // Auto-refresh every 60s
  useEffect(() => {
    const interval = setInterval(fetchCheckpoints, 60000)
    return () => clearInterval(interval)
  }, [])

  const handleResume = async (ckpt: Checkpoint) => {
    if (!confirm(`Resume training from step ${ckpt.step}?\n\nCheckpoint: ${ckpt.path}\nThis will stop any current training and restart from this step.`)) return
    setResuming(ckpt.name)
    try {
      const res = await api.post('/checkpoints/resume', null, {
        params: { checkpoint_path: ckpt.path, tpu_name: ckpt.tpu }
      })
      if (res.data.success) {
        alert(`Resumed from step ${ckpt.step}! Go to TRAINING panel to monitor.`)
      } else {
        alert(`Resume failed: ${res.data.error}`)
      }
    } catch (e: any) {
      alert(`Error: ${e.message}`)
    }
    setResuming(null)
  }

  const handleDownload = async (ckpt: Checkpoint) => {
    setDownloading(ckpt.name)
    try {
      const url = `/api/checkpoints/download/${ckpt.name}?run=${encodeURIComponent(ckpt.run)}&tpu_name=${ckpt.tpu}`
      const password = localStorage.getItem('lolm_password') || ''
      // Open download in new window with auth header via fetch+blob
      const resp = await fetch(url, { headers: { 'X-API-Key': password } })
      if (resp.ok) {
        const blob = await resp.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = ckpt.name
        a.click()
        URL.revokeObjectURL(a.href)
      } else {
        alert('Download failed')
      }
    } catch (e: any) {
      alert(`Download error: ${e.message}`)
    }
    setDownloading(null)
  }

  const handleDelete = async (ckpt: Checkpoint) => {
    if (!confirm(`Delete ${ckpt.name} (step ${ckpt.step}, ${ckpt.size_gb}GB)?\n\nThis cannot be undone.`)) return
    try {
      await api.delete(`/checkpoints/${ckpt.name}`, {
        params: { run: ckpt.run, tpu_name: ckpt.tpu }
      })
      fetchCheckpoints()
    } catch {}
  }

  // Group by run
  const runGroups: Record<string, Checkpoint[]> = {}
  for (const ckpt of checkpoints) {
    const run = ckpt.run || 'unknown'
    if (!runGroups[run]) runGroups[run] = []
    runGroups[run].push(ckpt)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Checkpoints</h2>
        <button onClick={fetchCheckpoints} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-surface-2 text-muted text-xs rounded hover:text-white">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {checkpoints.length === 0 ? (
        <Card>
          <div className="text-center py-8">
            <HardDrive size={24} className="text-muted mx-auto mb-2" />
            <p className="text-muted text-sm">{loading ? 'Loading checkpoints from TPU...' : 'No checkpoints found on the TPU.'}</p>
            <p className="text-[10px] text-muted mt-1">Checkpoints are saved every 500 steps during training.</p>
          </div>
        </Card>
      ) : (
        Object.entries(runGroups).map(([run, ckpts]) => (
          <Card key={run} title={`${run}`}>
            <div className="space-y-2">
              {ckpts.map((ckpt, i) => (
                <div key={ckpt.name}
                  className={`flex items-center justify-between p-3 rounded ${i === 0 ? 'bg-accent/5 border border-accent/20' : 'bg-surface-2'}`}>
                  <div className="flex items-center gap-3">
                    <Save size={14} className={i === 0 ? 'text-accent' : 'text-muted'} />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-white">Step {ckpt.step.toLocaleString()}</span>
                        {i === 0 && <StatusBadge status="LATEST" />}
                      </div>
                      <p className="text-[10px] text-muted mt-0.5">
                        {ckpt.size_gb} GB • {new Date(ckpt.timestamp * 1000).toLocaleString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <button
                      onClick={() => handleResume(ckpt)}
                      disabled={resuming === ckpt.name}
                      className="flex items-center gap-1 px-2 py-1 bg-success/10 text-success text-[10px] rounded hover:bg-success/20 disabled:opacity-50"
                    >
                      <Play size={10} /> {resuming === ckpt.name ? 'Resuming...' : 'Resume'}
                    </button>
                    <button
                      onClick={() => handleDownload(ckpt)}
                      disabled={downloading === ckpt.name}
                      className="flex items-center gap-1 px-2 py-1 bg-accent/10 text-accent text-[10px] rounded hover:bg-accent/20 disabled:opacity-50"
                    >
                      <Download size={10} /> {downloading === ckpt.name ? 'Downloading...' : 'Download'}
                    </button>
                    <button
                      onClick={() => handleDelete(ckpt)}
                      className="flex items-center gap-1 px-2 py-1 bg-danger/10 text-danger text-[10px] rounded hover:bg-danger/20"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))
      )}

      <Card>
        <div className="text-[10px] text-muted space-y-1">
          <p><strong>Auto-cleanup:</strong> Only the 2 most recent checkpoints are kept per run. Older ones are deleted automatically to prevent disk full crashes.</p>
          <p><strong>Resume:</strong> Click Resume to restart training from any checkpoint. The dashboard will SSH to all 4 TPU workers and launch with --resume.</p>
          <p><strong>Download:</strong> Downloads the checkpoint file (~11GB) directly from the TPU to your device via streaming.</p>
        </div>
      </Card>
    </div>
  )
}
