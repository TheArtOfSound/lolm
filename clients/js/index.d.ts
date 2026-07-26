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
  /** "social" | "question" | "task" */
  profile?: string;
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
  /** "social" | "question" | "task" */
  profile?: string;
  head_trained: boolean;
  memory_used: Array<Record<string, any>>;
  evidence: Array<Record<string, any>>;
  draft: string;
  result: Record<string, any>;
  base: Record<string, any>;
  timeline: DecisionEntry[];
  counters: Record<string, number>;
  ended_by: string;
  /** Harness-assembled account of what the agent actually did. */
  provenance?: string[];
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
  /** Prior turns of THIS conversation → in-conversation memory. */
  history?: Array<{ role: string; content: string }>;
  /** Durable facts about the user → cross-session memory. */
  memory?: string[];
  body?: Record<string, any>;
  signal?: AbortSignal;
  fetch?: typeof fetch;
}

export interface UserMemory {
  id: string;
  text: string;
  kind: string;
  source_conv: string;
  created_at: string;
  owner?: string;
}

export interface VisualResult {
  html: string;
  bytes: number;
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

/** Build a self-contained, sandboxed visual app (game/animation/page) from a prompt. */
export function buildVisual(opts: {
  task: string;
  baseUrl?: string;
  fetch?: typeof fetch;
  signal?: AbortSignal;
}): Promise<VisualResult>;

export interface CodeReceipt {
  kind?: string;
  task?: string;
  summary?: string;
  verdict?: string;
  ok?: boolean;
  receipt_sha?: string;
  ledger_sha?: string;
  prev_ledger_sha?: string | null;
  files?: string[];
  green_runs?: number;
  failed_runs?: number;
  verifies?: number;
  expected?: string[];
  expected_ok?: boolean;
  trail?: Array<Record<string, any>>;
  [key: string]: any;
}

export interface CodeDoneResult {
  summary?: string;
  ran?: boolean;
  produced_output?: boolean;
  ok?: boolean;
  verdict?: string;
  receipt_sha?: string;
  files?: string[];
  /** Sealed receipt when the stream emitted `code_receipt`. */
  receipt?: CodeReceipt | null;
  [key: string]: any;
}

/** Run the agentic coding loop (writes + runs real code in a jail, streamed). */
export function runCode(opts: {
  task: string;
  baseUrl?: string;
  maxSteps?: number;
  history?: Array<{ role: string; content: string }>;
  onEvent?(ev: ProtocolEvent): void;
  onCodeDone?(done: CodeDoneResult): void;
  onCodeReceipt?(receipt: CodeReceipt): void;
  signal?: AbortSignal;
  fetch?: typeof fetch;
}): Promise<CodeDoneResult>;

/** Recent sealed code receipts from the public audit ledger. */
export function listCodeReceipts(opts?: {
  baseUrl?: string;
  limit?: number;
  fetch?: typeof fetch;
}): Promise<{ receipts: CodeReceipt[]; stats: Record<string, any> }>;

/** List durable facts remembered about a user (cross-session memory). */
export function getMemory(opts?: {
  owner?: string;
  baseUrl?: string;
  fetch?: typeof fetch;
}): Promise<UserMemory[]>;

/** Remember a durable fact (verbatim, or `extract:true` to mine it from a message). */
export function rememberFact(opts: {
  text: string;
  owner?: string;
  extract?: boolean;
  baseUrl?: string;
  fetch?: typeof fetch;
}): Promise<{ saved: UserMemory | UserMemory[] | null; duplicate?: boolean }>;

/** Forget one fact by id, or `all:true` to clear everything for this owner. */
export function forgetMemory(opts: {
  id?: string;
  all?: boolean;
  owner?: string;
  baseUrl?: string;
  fetch?: typeof fetch;
}): Promise<{ deleted?: boolean; cleared?: number }>;
