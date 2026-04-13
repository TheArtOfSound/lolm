// LOLM Command Center — TypeScript interfaces matching lolm/config.py

export interface TPUInstance {
  name: string
  state: 'CREATING' | 'READY' | 'DELETING' | 'PREEMPTED' | 'STOPPED' | 'UNKNOWN'
  health: string
  acceleratorType: string
  runtimeVersion: string
  networkEndpoints: Array<{ ipAddress: string }>
  schedulingConfig: { spot?: boolean }
  createTime: string
}

export interface StepMetric {
  step: number
  loss?: number
  loss_tok?: number
  loss_future?: number
  loss_changepoint?: number
  loss_regime?: number
  loss_competitive?: number
  loss_mem?: number
  loss_manifest?: number
  lr?: number
  ppl?: number
  gate?: number
  regimes?: number
  steps_per_sec?: number
  tokens_total?: number
}

export interface TrainingJob {
  tpu_name: string
  zone: string
  config: string
  resume?: string
  gcs_path?: string
  started_at: string
  status: 'running' | 'stopped' | 'failed' | 'completed'
}

export interface TrainingStatus {
  running: boolean
  log_tail: string[]
  job: TrainingJob | null
}

export interface ConfigFile {
  name: string
  path: string
}

export interface Checkpoint {
  name: string
  path: string
  size_gb: number
  date: string
  step: number
}

export interface Run {
  id: string
  name: string
  config_snapshot: Record<string, any>
  tpu_name: string
  tpu_type: string
  tpu_zone: string
  gcs_path?: string
  status: string
  current_step: number
  max_steps: number
  started_at: string
  ended_at?: string
  error_message?: string
}

export type Panel = 'tpu' | 'config' | 'dataset' | 'training' | 'checkpoints' | 'experiments' | 'quicklaunch' | 'results' | 'chat' | 'eval' | 'ship'
