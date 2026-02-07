import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type MessageRole = 'user' | 'agent'
type RoleType = 'facilitator' | 'character'

type ChatMessage = {
  role: MessageRole
  speaker_id: string
  content: string
  timestamp: string
}

type Agent = {
  agent_id: string
  model: string
  display_name: string
  role_type: RoleType
  character_profile: string
}

type RoomPayload = {
  room_id: string
  subject: string
  agents: Agent[]
}

type SnapshotPayload = {
  room_id: string
  subject: string
  running: boolean
  current_act: string
  rounds_completed: number
  end_reason?: string | null
  generation_logs?: GenerationLog[]
  agents: Agent[]
  messages: ChatMessage[]
}

type SocketEvent = {
  type: 'room_snapshot' | 'room_state' | 'message' | 'generation_log' | 'error'
  payload: unknown
}

type Highlights = {
  quote: string
  conflict: string
  agreement: string
}

type GenerationLog = {
  round_index: number
  model: string
  display_name: string
  act: string
  status: 'requesting' | 'completed' | 'failed'
  detail: string
  timestamp: string
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

const CONFLICT_HINTS = ['しかし', 'でも', '一方', 'ただ', '反対', '懸念']
const AGREEMENT_HINTS = ['結論', '合意', '一致', '最終的に', 'まとめると', 'これでいく']

function deriveHighlights(messages: ChatMessage[]): Highlights {
  const agentMessages = messages.filter((message) => message.role === 'agent')
  if (agentMessages.length === 0) {
    return {
      quote: '会話が進むと、ここに刺さった一言が表示されます。',
      conflict: '対立点はまだありません。',
      agreement: '合意点はまだありません。',
    }
  }

  const quoteSource = [...agentMessages]
    .reverse()
    .find((message) => message.speaker_id !== '総括')
  const quote = quoteSource?.content ?? agentMessages[agentMessages.length - 1].content

  const conflictSource = [...agentMessages]
    .reverse()
    .find((message) => CONFLICT_HINTS.some((hint) => message.content.includes(hint)))
  const conflict = conflictSource?.content ?? '対立点はまだ抽出中です。'

  const agreementSource = [...agentMessages]
    .reverse()
    .find((message) => AGREEMENT_HINTS.some((hint) => message.content.includes(hint)))
  const agreement = agreementSource?.content ?? '合意点はまだ抽出中です。'

  return { quote, conflict, agreement }
}

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

  const [subject, setSubject] = useState('')
  const [selectedModels, setSelectedModels] = useState<string[]>(MODEL_OPTIONS.slice(0, 3))
  const [room, setRoom] = useState<RoomPayload | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [generationLogs, setGenerationLogs] = useState<GenerationLog[]>([])
  const [userInput, setUserInput] = useState('')
  const [running, setRunning] = useState(false)
  const [currentAct, setCurrentAct] = useState('導入')
  const [roundsCompleted, setRoundsCompleted] = useState(0)
  const [status, setStatus] = useState('お題を入れて部屋を作成してください。')
  const socketRef = useRef<WebSocket | null>(null)

  const highlights = useMemo(() => deriveHighlights(messages), [messages])

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
      setStatus('接続中です。会話観戦を開始できます。')
    }

    socket.onmessage = (event) => {
      const parsed = JSON.parse(event.data) as SocketEvent
      if (parsed.type === 'room_snapshot') {
        const payload = parsed.payload as SnapshotPayload
        setRoom({
          room_id: payload.room_id,
          subject: payload.subject,
          agents: payload.agents ?? [],
        })
        setMessages(payload.messages ?? [])
        setGenerationLogs(payload.generation_logs ?? [])
        setRunning(payload.running)
        setCurrentAct(payload.current_act ?? '導入')
        setRoundsCompleted(payload.rounds_completed ?? 0)
        return
      }
      if (parsed.type === 'room_state') {
        const payload = parsed.payload as {
          running: boolean
          current_act?: string
          rounds_completed?: number
          end_reason?: string | null
        }
        setRunning(payload.running)
        if (payload.current_act) {
          setCurrentAct(payload.current_act)
        }
        if (typeof payload.rounds_completed === 'number') {
          setRoundsCompleted(payload.rounds_completed)
        }
        if (!payload.running && payload.end_reason) {
          setStatus(`会話を終了しました: ${payload.end_reason}`)
        }
        return
      }
      if (parsed.type === 'message') {
        const payload = parsed.payload as ChatMessage
        setMessages((prev) => [...prev, payload])
        return
      }
      if (parsed.type === 'generation_log') {
        const payload = parsed.payload as GenerationLog
        setGenerationLogs((prev) => [...prev, payload].slice(-120))
        if (payload.status === 'requesting') {
          setStatus(`アクセス中: ${payload.display_name} (${payload.act})`)
        } else if (payload.status === 'failed') {
          setStatus(`呼び出し失敗: ${payload.display_name}`)
        }
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
    const cleanSubject = subject.trim()
    if (!cleanSubject) {
      setStatus('議論したいお題を入力してください。')
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
          subject: cleanSubject,
          models: selectedModels,
        }),
      })
      setRoom(payload)
      setMessages([])
      setGenerationLogs([])
      setCurrentAct('導入')
      setRoundsCompleted(0)
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
    setGenerationLogs([])
    setCurrentAct('導入')
    setRoundsCompleted(0)
    setRunning(false)
    setStatus('新しい部屋を作成してください。')
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">LLM CHAT ROOM</p>
        <h1>モデル同士の会話を観戦する</h1>
        <p className="status">{status}</p>
      </header>

      {!room ? (
        <section className="setup-card">
          <label className="field">
            <span>議論するお題</span>
            <textarea
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder="例: 1時間で作れる面白いWebサービス案を考える"
              rows={3}
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
                <p>お題: {room.subject}</p>
              </div>
              <div className="toolbar-badges">
                <span className="act-badge">幕: {currentAct}</span>
                <span className="act-badge">発話: {roundsCompleted}</span>
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

            <section className="highlights">
              <article className="highlight-card">
                <h3>刺さった一言</h3>
                <p>{highlights.quote}</p>
              </article>
              <article className="highlight-card">
                <h3>対立点</h3>
                <p>{highlights.conflict}</p>
              </article>
              <article className="highlight-card">
                <h3>合意点</h3>
                <p>{highlights.agreement}</p>
              </article>
            </section>

            <ul className="message-list">
              {messages.length === 0 ? (
                <li className="empty">会話はまだありません。開始してみましょう。</li>
              ) : (
                messages.map((message, index) => (
                  <li
                    key={`${message.timestamp}-${index}`}
                    className={`msg msg-${message.role} ${
                      message.speaker_id === '総括' ? 'msg-summary' : ''
                    } ${message.speaker_id === 'お題カード' ? 'msg-card' : ''}`}
                  >
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
                placeholder="途中で話を振るときに入力"
              />
              <button className="primary" type="submit">
                送信
              </button>
            </form>
          </article>

          <aside className="members-panel">
            <h2>参加モデル</h2>
            <p className="members-note">役割は自動設定です（司会1名 + キャラクター）。</p>
            <ul className="members-list">
              {room.agents.map((agent) => (
                <li key={agent.agent_id} className="member-item">
                  <p className="member-name">{agent.display_name}</p>
                  <p className="member-role">
                    {agent.role_type === 'facilitator' ? 'ファシリテーター' : 'キャラクター'}
                  </p>
                  {agent.role_type === 'character' && (
                    <p className="member-character">{agent.character_profile}</p>
                  )}
                </li>
              ))}
            </ul>
            <section className="logs-panel">
              <h3>アクセスログ</h3>
              <ul className="logs-list">
                {generationLogs.length === 0 ? (
                  <li className="log-empty">ログはまだありません。</li>
                ) : (
                  generationLogs.map((log, index) => (
                    <li key={`${log.timestamp}-${index}`} className={`log-item log-${log.status}`}>
                      <p className="log-main">
                        R{log.round_index} {log.status} {log.display_name}
                      </p>
                      <p className="log-sub">
                        幕: {log.act}
                        {log.detail ? ` / ${log.detail}` : ''}
                      </p>
                    </li>
                  ))
                )}
              </ul>
            </section>
          </aside>
        </section>
      )}
    </main>
  )
}

export default App
