import { useState, useEffect, useRef } from 'react'
import { MessageSquare, Send, Loader2, Clock, Trash2 } from 'lucide-react'
import Card from '../components/Card'
import api from '../api'

interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  step?: number
  checkpoint?: string
  timestamp?: string
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'system', content: 'Chat with your LOLM model at any checkpoint. The model loads on CPU (separate from training) so it never interrupts the active run. Early checkpoints will produce rough text — quality improves with training.' }
  ])
  const [input, setInput] = useState('')
  const [generating, setGenerating] = useState(false)
  const [checkpoints, setCheckpoints] = useState<{ path: string; name: string; step: number }[]>([])
  const [selectedCheckpoint, setSelectedCheckpoint] = useState('')
  const [temperature, setTemperature] = useState(0.8)
  const [maxTokens, setMaxTokens] = useState(100)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Load available checkpoints
  useEffect(() => {
    api.get('/chat/checkpoints', { params: { tpu_name: 'lolm-7b' } })
      .then(r => {
        const ckpts = r.data.checkpoints || []
        setCheckpoints(ckpts)
        if (ckpts.length > 0) setSelectedCheckpoint(ckpts[ckpts.length - 1].path)
      })
      .catch(() => {})

    // Refresh checkpoints every 2 min
    const interval = setInterval(() => {
      api.get('/chat/checkpoints', { params: { tpu_name: 'lolm-7b' } })
        .then(r => {
          const ckpts = r.data.checkpoints || []
          setCheckpoints(ckpts)
          if (ckpts.length > 0 && !selectedCheckpoint) setSelectedCheckpoint(ckpts[ckpts.length - 1].path)
        })
        .catch(() => {})
    }, 120000)
    return () => clearInterval(interval)
  }, [])

  // Load chat history
  useEffect(() => {
    api.get('/chat/history', { params: { limit: 20 } })
      .then(r => {
        const history = r.data.chats || []
        if (history.length > 0) {
          const restored: ChatMessage[] = [messages[0]] // Keep system msg
          history.forEach((h: any) => {
            restored.push({ role: 'user', content: h.prompt, timestamp: h.timestamp })
            restored.push({
              role: 'assistant', content: h.response,
              step: h.step, checkpoint: h.checkpoint, timestamp: h.timestamp
            })
          })
          setMessages(restored)
        }
      })
      .catch(() => {})
  }, [])

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || generating) return
    const prompt = input.trim()
    setInput('')

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: prompt }])
    setGenerating(true)

    try {
      const res = await api.post('/chat/generate', null, {
        params: {
          prompt,
          checkpoint: selectedCheckpoint,
          max_tokens: maxTokens,
          temperature,
          tpu_name: 'lolm-7b',
        },
        timeout: 180000, // 3 min for loading model + generating
      })

      if (res.data.error) {
        setMessages(prev => [...prev, {
          role: 'system',
          content: `Error: ${res.data.error}`
        }])
      } else {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: res.data.response || '(empty response)',
          step: res.data.step,
          checkpoint: res.data.checkpoint,
        }])
      }
    } catch (e: any) {
      setMessages(prev => [...prev, {
        role: 'system',
        content: `Error: ${e.message}. The model may still be loading (takes ~30-60s for 1B on CPU).`
      }])
    }
    setGenerating(false)
  }

  return (
    <div className="space-y-3 h-full flex flex-col">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare size={20} className="text-accent" />
          <h2 className="text-lg font-bold">Chat with LOLM</h2>
        </div>
        <button
          onClick={() => setMessages([messages[0]])}
          className="flex items-center gap-1 px-2 py-1 text-muted text-[10px] hover:text-white"
        >
          <Trash2 size={10} /> Clear
        </button>
      </div>

      {/* Settings bar */}
      <div className="flex flex-wrap gap-2 items-center bg-surface border border-border rounded-lg p-2">
        <div className="flex-1 min-w-[150px]">
          <label className="text-[9px] text-muted block mb-0.5">Checkpoint</label>
          <select
            value={selectedCheckpoint}
            onChange={e => setSelectedCheckpoint(e.target.value)}
            className="w-full bg-bg border border-border rounded px-2 py-1 text-[11px] text-white"
          >
            {checkpoints.length === 0 ? (
              <option value="">No checkpoints yet (saves every 500 steps)</option>
            ) : (
              checkpoints.map(c => (
                <option key={c.path} value={c.path}>Step {c.step.toLocaleString()} — {c.name}</option>
              ))
            )}
            <option value="">Latest available</option>
          </select>
        </div>
        <div className="w-20">
          <label className="text-[9px] text-muted block mb-0.5">Temp</label>
          <input
            type="number" step="0.1" min="0.1" max="2.0"
            value={temperature} onChange={e => setTemperature(parseFloat(e.target.value))}
            className="w-full bg-bg border border-border rounded px-2 py-1 text-[11px] text-white"
          />
        </div>
        <div className="w-20">
          <label className="text-[9px] text-muted block mb-0.5">Tokens</label>
          <input
            type="number" step="10" min="10" max="500"
            value={maxTokens} onChange={e => setMaxTokens(parseInt(e.target.value))}
            className="w-full bg-bg border border-border rounded px-2 py-1 text-[11px] text-white"
          />
        </div>
      </div>

      {/* Chat messages */}
      <div className="flex-1 bg-surface border border-border rounded-lg p-3 overflow-y-auto min-h-[300px] max-h-[500px]">
        {messages.map((msg, i) => (
          <div key={i} className={`mb-3 ${msg.role === 'user' ? 'text-right' : ''}`}>
            {msg.role === 'system' ? (
              <div className="bg-accent/10 text-accent text-[11px] p-2 rounded inline-block max-w-[90%]">
                {msg.content}
              </div>
            ) : msg.role === 'user' ? (
              <div className="bg-accent/20 text-white text-[11px] p-2 rounded-lg inline-block max-w-[80%] text-left">
                {msg.content}
              </div>
            ) : (
              <div className="bg-surface-2 text-gray-300 text-[11px] p-3 rounded-lg inline-block max-w-[90%] text-left">
                <div className="whitespace-pre-wrap font-mono leading-relaxed">{msg.content}</div>
                {msg.step != null && (
                  <div className="mt-2 pt-2 border-t border-border/50 flex items-center gap-2 text-[9px] text-muted">
                    <Clock size={8} />
                    <span>Step {msg.step.toLocaleString()}</span>
                    {msg.checkpoint && <span>• {msg.checkpoint}</span>}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {generating && (
          <div className="flex items-center gap-2 text-muted text-[11px]">
            <Loader2 size={12} className="animate-spin" />
            Loading checkpoint + generating (30-60s for 1B model on CPU)...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder={checkpoints.length === 0 ? "Waiting for first checkpoint (step 500)..." : "Type a prompt to send to LOLM..."}
          disabled={generating || checkpoints.length === 0}
          className="flex-1 bg-bg border border-border rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-muted disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={generating || !input.trim() || checkpoints.length === 0}
          className="px-4 py-2.5 bg-accent text-white rounded-lg hover:bg-accent-2 disabled:opacity-50 flex items-center gap-2"
        >
          {generating ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  )
}
