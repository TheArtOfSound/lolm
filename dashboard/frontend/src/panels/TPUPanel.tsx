import { useEffect, useState } from 'react'
import { Cpu, Plus, Trash2, RefreshCw, Wifi } from 'lucide-react'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { useStore } from '../store'
import api from '../api'
import type { TPUInstance } from '../types'

export default function TPUPanel() {
  const tpus = useStore(s => s.tpus)
  const setTpus = useStore(s => s.setTpus)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('lolm-7b')
  const [newType, setNewType] = useState('v4-32')
  const [newSpot, setNewSpot] = useState(true)
  const [health, setHealth] = useState<Record<string, any>>({})

  const fetchTPUs = async () => {
    setLoading(true)
    try {
      const res = await api.get('/tpu/list')
      setTpus(res.data.tpus || [])
    } catch {}
    setLoading(false)
  }

  useEffect(() => { fetchTPUs() }, [])

  const createTPU = async () => {
    setCreating(true)
    try {
      await api.post('/tpu/create', null, {
        params: { name: newName, accelerator_type: newType, spot: newSpot }
      })
      setShowCreate(false)
      await fetchTPUs()
    } catch {}
    setCreating(false)
  }

  const deleteTPU = async (name: string) => {
    if (!confirm(`Delete TPU "${name}"? This cannot be undone.`)) return
    try {
      await api.delete(`/tpu/${name}`)
      await fetchTPUs()
    } catch {}
  }

  const checkHealth = async (name: string) => {
    try {
      const res = await api.get(`/tpu/${name}/health`)
      setHealth(prev => ({ ...prev, [name]: res.data }))
    } catch {}
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">TPU Management</h2>
        <div className="flex gap-2">
          <button onClick={fetchTPUs} className="flex items-center gap-2 px-3 py-1.5 bg-surface-2 text-muted text-xs rounded hover:text-white">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={() => setShowCreate(!showCreate)} className="flex items-center gap-2 px-3 py-1.5 bg-accent/20 text-accent text-xs rounded hover:bg-accent/30">
            <Plus size={14} /> Create TPU
          </button>
        </div>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card title="Create New TPU VM">
          <div className="grid grid-cols-4 gap-3">
            <div>
              <label className="text-[10px] text-muted block mb-1">Name</label>
              <input value={newName} onChange={e => setNewName(e.target.value)}
                className="w-full bg-bg border border-border rounded px-2 py-1.5 text-xs text-white" />
            </div>
            <div>
              <label className="text-[10px] text-muted block mb-1">Accelerator</label>
              <select value={newType} onChange={e => setNewType(e.target.value)}
                className="w-full bg-bg border border-border rounded px-2 py-1.5 text-xs text-white">
                <option value="v4-32">v4-32 (16 chips, 32GB/chip)</option>
                <option value="v4-8">v4-8 (4 chips, 32GB/chip)</option>
                <option value="v6e-64">v6e-64 (64 chips, 16GB/chip)</option>
                <option value="v5e-64">v5e-64 (64 chips, 16GB/chip)</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" checked={newSpot} onChange={e => setNewSpot(e.target.checked)}
                  className="accent-accent" />
                Spot (cheaper, can be preempted)
              </label>
            </div>
            <div className="flex items-end">
              <button onClick={createTPU} disabled={creating}
                className="px-4 py-1.5 bg-accent text-white text-xs rounded hover:bg-accent-2 disabled:opacity-50">
                {creating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </Card>
      )}

      {/* TPU List */}
      {tpus.length === 0 ? (
        <Card>
          <p className="text-muted text-sm text-center py-8">
            {loading ? 'Loading TPU VMs...' : 'No TPU VMs found. Create one to get started.'}
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {tpus.map((tpu: TPUInstance) => (
            <Card key={tpu.name}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Cpu size={20} className="text-accent" />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white">{tpu.name}</span>
                      <StatusBadge status={tpu.state} />
                      {tpu.schedulingConfig?.spot && (
                        <span className="text-[9px] text-warning bg-warning/10 px-1.5 py-0.5 rounded">SPOT</span>
                      )}
                    </div>
                    <p className="text-[10px] text-muted mt-0.5">
                      {tpu.acceleratorType} • {tpu.networkEndpoints?.[0]?.ipAddress || 'no IP'}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => checkHealth(tpu.name)}
                    className="flex items-center gap-1 px-2 py-1 bg-surface-2 text-muted text-[10px] rounded hover:text-white">
                    <Wifi size={12} /> Health
                  </button>
                  <button onClick={() => deleteTPU(tpu.name)}
                    className="flex items-center gap-1 px-2 py-1 bg-danger/10 text-danger text-[10px] rounded hover:bg-danger/20">
                    <Trash2 size={12} /> Delete
                  </button>
                </div>
              </div>
              {health[tpu.name] && (
                <div className="mt-3 pt-3 border-t border-border grid grid-cols-3 gap-3 text-xs">
                  <div>
                    <span className="text-muted">Accel: </span>
                    <span className={health[tpu.name].accel_status === 'FREE' ? 'text-success' : 'text-warning'}>
                      {health[tpu.name].accel_status}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted">Python procs: </span>
                    <span className="text-white">{health[tpu.name].python_processes}</span>
                  </div>
                  <div>
                    <span className="text-muted">Memory: </span>
                    <span className="text-white">{health[tpu.name].memory}</span>
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
