import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type MessageRole = 'user' | 'agent'

type ChatMessage = {
  role: MessageRole
  speaker_id: string
  content: string
  timestamp: string
}

type Persona = {
  agent_id: string
  model: string
  persona_prompt: string
}

type RoomPayload = {
  room_id: string
  topic: string
  personas: Persona[]
}

type SnapshotPayload = {
  room_id: string
  topic: string
  running: boolean
  messages: ChatMessage[]
}

type SocketEvent = {
  type: 'room_snapshot' | 'room_state' | 'message' | 'error'
  payload: unknown
}

const MODEL_OPTIONS = [
  'openai/gpt-4o-mini',
  'anthropic/claude-3.5-sonnet',
  'google/gemini-2.0-flash',
  'meta-llama/llama-3.3-70b-instruct',
  'moonshotai/kimi-k2.5',
  'google/gemini-3-flash-preview',
  'anthropic/claude-sonnet-4.5',
  'x-ai/grok-4.1-fast',
]

async function requestJson<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.text()
    throw new Error(body || 'Request failed.')
  }
  return (await response.json()) as T
}

function App() {
  const apiBase = useMemo(
    () => (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, ''),
    [],
  )
  const wsBase = useMemo(() => apiBase.replace(/^http/, 'ws'), [apiBase])

  const [topic, setTopic] = useState('')
  const [selectedModels, setSelectedModels] = useState<string[]>(MODEL_OPTIONS.slice(0, 3))
  const [room, setRoom] = useState<RoomPayload | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [userInput, setUserInput] = useState('')
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState('アイデアを入れて部屋を作成してください。')
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    return () => {
      if (socketRef.current) {
        socketRef.current.close()
      }
    }
  }, [])

  const connectWebSocket = (roomId: string) => {
    if (socketRef.current) {
      socketRef.current.close()
    }
    const socket = new WebSocket(`${wsBase}/ws/room/${roomId}`)

    socket.onopen = () => {
      setStatus('接続中です。開始ボタンで会話を回せます。')
    }

    socket.onmessage = (event) => {
      const parsed = JSON.parse(event.data) as SocketEvent
      if (parsed.type === 'room_snapshot') {
        const payload = parsed.payload as SnapshotPayload
        setRunning(payload.running)
        setMessages(payload.messages ?? [])
        return
      }
      if (parsed.type === 'room_state') {
        const payload = parsed.payload as { running: boolean }
        setRunning(payload.running)
        return
      }
      if (parsed.type === 'message') {
        const payload = parsed.payload as ChatMessage
        setMessages((prev) => [...prev, payload])
        return
      }
      if (parsed.type === 'error') {
        const payload = parsed.payload as { detail?: string }
        setStatus(payload.detail ?? 'エラーが発生しました。')
      }
    }

    socket.onclose = () => {
      setStatus((prev) => (prev.includes('エラー') ? prev : '接続が閉じられました。'))
    }

    socketRef.current = socket
  }

  const toggleModel = (model: string) => {
    setSelectedModels((prev) => {
      if (prev.includes(model)) {
        return prev.filter((item) => item !== model)
      }
      return [...prev, model]
    })
  }

  const createRoom = async () => {
    const cleanTopic = topic.trim()
    if (!cleanTopic) {
      setStatus('テーマを入力してください。')
      return
    }
    if (selectedModels.length === 0) {
      setStatus('最低1モデルを選択してください。')
      return
    }

    try {
      const payload = await requestJson<RoomPayload>(`${apiBase}/api/room/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: cleanTopic,
          models: selectedModels,
        }),
      })
      setRoom(payload)
      setMessages([])
      setRunning(false)
      setStatus(`部屋 ${payload.room_id} を作成しました。`)
      connectWebSocket(payload.room_id)
    } catch (error) {
      setStatus(`部屋作成に失敗しました: ${String(error)}`)
    }
  }

  const startChat = async () => {
    if (!room) return
    try {
      await requestJson<{ status: string }>(`${apiBase}/api/room/${room.room_id}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      setStatus('会話を開始しました。')
    } catch (error) {
      setStatus(`開始に失敗しました: ${String(error)}`)
    }
  }

  const stopChat = async () => {
    if (!room) return
    try {
      await requestJson<{ status: string }>(`${apiBase}/api/room/${room.room_id}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      setStatus('会話を停止しました。')
    } catch (error) {
      setStatus(`停止に失敗しました: ${String(error)}`)
    }
  }

  const submitUserMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!room) return
    const content = userInput.trim()
    if (!content) return
    try {
      await requestJson<{ status: string }>(`${apiBase}/api/room/${room.room_id}/user-message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      setUserInput('')
    } catch (error) {
      setStatus(`投稿に失敗しました: ${String(error)}`)
    }
  }

  const resetRoom = () => {
    if (socketRef.current) {
      socketRef.current.close()
      socketRef.current = null
    }
    setRoom(null)
    setMessages([])
    setRunning(false)
    setStatus('新しい部屋を作成してください。')
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">LLM CHAT ROOM</p>
        <h1>複数LLMで雑談ルーム</h1>
        <p className="status">{status}</p>
      </header>

      {!room ? (
        <section className="setup-card">
          <label className="field">
            <span>トピック</span>
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="例: 最高の深夜メシは何か"
            />
          </label>
          <div className="field">
            <span>参加モデル</span>
            <div className="model-grid">
              {MODEL_OPTIONS.map((model) => (
                <label key={model} className="model-item">
                  <input
                    type="checkbox"
                    checked={selectedModels.includes(model)}
                    onChange={() => toggleModel(model)}
                  />
                  <span>{model}</span>
                </label>
              ))}
            </div>
          </div>
          <button className="primary" onClick={createRoom}>
            部屋を作る
          </button>
        </section>
      ) : (
        <section className="room-layout">
          <article className="chat-panel">
            <div className="toolbar">
              <div>
                <strong>Room: {room.room_id}</strong>
                <p>{room.topic}</p>
              </div>
              <div className="toolbar-buttons">
                <button className="primary" onClick={startChat} disabled={running}>
                  開始
                </button>
                <button onClick={stopChat} disabled={!running}>
                  停止
                </button>
                <button onClick={resetRoom}>リセット</button>
              </div>
            </div>

            <ul className="message-list">
              {messages.length === 0 ? (
                <li className="empty">会話はまだありません。開始してみましょう。</li>
              ) : (
                messages.map((message, index) => (
                  <li key={`${message.timestamp}-${index}`} className={`msg msg-${message.role}`}>
                    <p className="meta">{message.speaker_id}</p>
                    <p>{message.content}</p>
                  </li>
                ))
              )}
            </ul>

            <form className="composer" onSubmit={submitUserMessage}>
              <input
                value={userInput}
                onChange={(event) => setUserInput(event.target.value)}
                placeholder="割り込み発言を入力"
              />
              <button className="primary" type="submit">
                送信
              </button>
            </form>
          </article>

          <aside className="persona-panel">
            <h2>参加エージェント</h2>
            <ul>
              {room.personas.map((persona) => (
                <li key={persona.agent_id} className="persona-card">
                  <h3>{persona.agent_id}</h3>
                  <p className="model">{persona.model}</p>
                  <p>{persona.persona_prompt}</p>
                </li>
              ))}
            </ul>
          </aside>
        </section>
      )}
    </main>
  )
}

export default App
