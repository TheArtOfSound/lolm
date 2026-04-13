import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { TPUInstance, StepMetric, TrainingStatus, Panel, ConfigFile, Checkpoint, Run } from './types'

interface Store {
  // Auth
  authenticated: boolean
  setAuthenticated: (v: boolean) => void

  // Navigation
  panel: Panel
  setPanel: (p: Panel) => void

  // TPU
  tpus: TPUInstance[]
  setTpus: (t: TPUInstance[]) => void

  // Configs
  configs: ConfigFile[]
  setConfigs: (c: ConfigFile[]) => void
  activeConfig: Record<string, any> | null
  setActiveConfig: (c: Record<string, any> | null) => void
  schema: Record<string, any> | null
  setSchema: (s: Record<string, any>) => void

  // Training
  trainingStatus: TrainingStatus | null
  setTrainingStatus: (s: TrainingStatus | null) => void
  liveMetrics: StepMetric[]
  addMetric: (m: StepMetric) => void
  clearMetrics: () => void
  logLines: string[]
  addLogLine: (line: string) => void
  clearLogs: () => void

  // Checkpoints
  checkpoints: Checkpoint[]
  setCheckpoints: (c: Checkpoint[]) => void

  // Runs
  runs: Run[]
  setRuns: (r: Run[]) => void
}

export const useStore = create<Store>()(
  persist(
    (set) => ({
      authenticated: false,
      setAuthenticated: (v) => set({ authenticated: v }),

      panel: 'training',
      setPanel: (p) => set({ panel: p }),

      tpus: [],
      setTpus: (t) => set({ tpus: t }),

      configs: [],
      setConfigs: (c) => set({ configs: c }),
      activeConfig: null,
      setActiveConfig: (c) => set({ activeConfig: c }),
      schema: null,
      setSchema: (s) => set({ schema: s }),

      trainingStatus: null,
      setTrainingStatus: (s) => set({ trainingStatus: s }),
      liveMetrics: [],
      addMetric: (m) => set((state) => ({
        liveMetrics: [...state.liveMetrics.slice(-2000), m]
      })),
      clearMetrics: () => set({ liveMetrics: [] }),
      logLines: [],
      addLogLine: (line) => set((state) => ({
        logLines: [...state.logLines.slice(-500), line]
      })),
      clearLogs: () => set({ logLines: [] }),

      checkpoints: [],
      setCheckpoints: (c) => set({ checkpoints: c }),

      runs: [],
      setRuns: (r) => set({ runs: r }),
    }),
    {
      name: 'lolm-command-center',
      partialize: (state) => ({
        authenticated: state.authenticated,
        panel: state.panel,
      }),
    }
  )
)
