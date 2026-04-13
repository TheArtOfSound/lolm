import { useEffect, useRef, useCallback } from 'react'
import { useStore } from '../store'

export function useWebSocket(tpuName: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const addMetric = useStore(s => s.addMetric)
  const addLogLine = useStore(s => s.addLogLine)

  const connect = useCallback(() => {
    if (!tpuName || wsRef.current?.readyState === WebSocket.OPEN) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/logs`)
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({ tpu_name: tpuName, zone: 'us-central2-b' }))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'step' && data.metrics) {
          addMetric(data.metrics)
        }
        if (data.line) {
          addLogLine(data.line)
        }
      } catch {
        // Non-JSON message
        addLogLine(event.data)
      }
    }

    ws.onclose = () => {
      // Auto-reconnect after 5s
      setTimeout(() => connect(), 5000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [tpuName, addMetric, addLogLine])

  useEffect(() => {
    connect()
    return () => {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return wsRef
}
