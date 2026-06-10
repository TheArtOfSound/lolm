export interface ProtocolEvent<T = any> {
  event: string;
  data: T;
}

export interface TokenEvent {
  token: string;
  channel: "draft" | "verify" | "final" | string;
  segment?: number;
  nfet?: {
    entropy?: number | null;
    drift?: number | null;
    gate?: number | null;
    regime?: number | null;
    control?: string | null;
  };
}

export interface DecisionEntry {
  segment: number;
  decision: {
    control: number;
    label: "continue" | "retrieve" | "verify" | "branch" | "finalize";
    source: "heuristic" | "head" | "budget" | "calibrating" | "cooldown";
    reason: string;
    zscores: Record<string, number>;
    head_probs?: number[] | null;
    step: number;
  };
  segment_tokens?: number;
  segment_mean_entropy?: number;
  telemetry_frames?: number;
}

export interface ActionEvent {
  segment: number;
  kind: "continue" | "retrieve" | "verify" | "branch" | "finalize";
  added?: number;
  verdict?: "ok" | "revise";
  chosen?: number;
  candidates?: Array<{ text: string; mean_entropy: number; tokens?: number }>;
  evidence?: Array<Record<string, any>>;
}

export interface ProofReceipt {
  verdict: string;
  plain: string;
  changed_text: boolean;
  word_similarity: number;
  control_counts: Record<string, number>;
  decision_sources: Record<string, number>;
  actions_taken: boolean;
  ended_by: string;
  head_trained: boolean;
  memory_hits_available: number;
  evidence_count: number;
}

export interface RunResult {
  command: string;
  reasoner: string;
  head_trained: boolean;
  memory_used: Array<Record<string, any>>;
  evidence: Array<Record<string, any>>;
  draft: string;
  result: Record<string, any>;
  base: Record<string, any>;
  timeline: DecisionEntry[];
  counters: Record<string, number>;
  ended_by: string;
  proof: ProofReceipt;
}

export interface Handlers {
  onEvent?(ev: ProtocolEvent): void;
  onToken?(t: TokenEvent): void;
  onDecision?(d: DecisionEntry): void;
  onAction?(a: ActionEvent): void;
  onProof?(p: ProofReceipt): void;
  onPhase?(p: { phase: string; ended_by?: string }): void;
}

export interface RunAgentOptions extends Handlers {
  baseUrl?: string;
  endpoint?: string;
  command: string;
  body?: Record<string, any>;
  signal?: AbortSignal;
  fetch?: typeof fetch;
}

export interface PlayReplayOptions extends Handlers {
  speed?: number;
  signal?: AbortSignal;
  fetch?: typeof fetch;
}

export interface DemoStatus {
  model_ready: boolean;
  busy: boolean;
  limits: Record<string, number>;
  runs_started: number;
  runs_completed: number;
  last_run_seconds: number | null;
  replays: number;
}

export class AgentRunError extends Error {
  status: number | null;
  body: any;
}

export function parseSSEStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<ProtocolEvent>;

export function runAgent(opts: RunAgentOptions): Promise<RunResult>;

export function playReplay(
  source: string | { events: ProtocolEvent[] } | ProtocolEvent[],
  opts?: PlayReplayOptions,
): Promise<RunResult | null>;

export function friendly(ev: ProtocolEvent): string | null;

export function getStatus(opts?: {
  baseUrl?: string;
  fetch?: typeof fetch;
  signal?: AbortSignal;
}): Promise<DemoStatus>;
