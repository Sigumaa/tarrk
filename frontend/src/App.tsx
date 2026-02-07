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
  persona_prompt: string
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
  agents: Agent[]
  messages: ChatMessage[]
}

type SocketEvent = {
  type: 'room_snapshot' | 'room_state' | 'message' | 'error'
  payload: unknown
}

type SetupDraft = {
  subject: string
  agents: Agent[]
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

function cloneAgents(agents: Agent[]): Agent[] {
  return agents.map((agent) => ({ ...agent }))
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
  const [draft, setDraft] = useState<SetupDraft | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [userInput, setUserInput] = useState('')
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState('お題を入れて部屋を作成してください。')
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
      setStatus('接続中です。開始前なら役割を編集できます。')
    }

    socket.onmessage = (event) => {
      const parsed = JSON.parse(event.data) as SocketEvent
      if (parsed.type === 'room_snapshot') {
        const payload = parsed.payload as SnapshotPayload
        const nextRoom: RoomPayload = {
          room_id: payload.room_id,
          subject: payload.subject,
          agents: payload.agents ?? [],
        }
        setRoom(nextRoom)
        setRunning(payload.running)
        setMessages(payload.messages ?? [])
        setDraft((current) =>
          current
            ? current
            : {
                subject: nextRoom.subject,
                agents: cloneAgents(nextRoom.agents),
              },
        )
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
      setDraft({ subject: payload.subject, agents: cloneAgents(payload.agents) })
      setMessages([])
      setRunning(false)
      setStatus(`部屋 ${payload.room_id} を作成しました。`)
      connectWebSocket(payload.room_id)
    } catch (error) {
      setStatus(`部屋作成に失敗しました: ${String(error)}`)
    }
  }

  const saveSetup = async (): Promise<boolean> => {
    if (!room || !draft) {
      return false
    }
    if (running) {
      setStatus('会話停止中のみ設定を更新できます。')
      return false
    }

    const facilitatorCount = draft.agents.filter((agent) => agent.role_type === 'facilitator').length
    if (facilitatorCount !== 1) {
      setStatus('ファシリテーターは1名だけ選んでください。')
      return false
    }

    try {
      const payload = await requestJson<RoomPayload>(`${apiBase}/api/room/${room.room_id}/setup`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: draft.subject.trim(),
          agents: draft.agents.map((agent) => ({
            agent_id: agent.agent_id,
            role_type: agent.role_type,
            character_profile:
              agent.role_type === 'character' ? agent.character_profile.trim() : '',
          })),
        }),
      })
      setRoom(payload)
      setDraft({ subject: payload.subject, agents: cloneAgents(payload.agents) })
      setStatus('設定を保存しました。')
      return true
    } catch (error) {
      setStatus(`設定保存に失敗しました: ${String(error)}`)
      return false
    }
  }

  const startChat = async () => {
    if (!room) return
    const saved = await saveSetup()
    if (!saved) return

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
    setDraft(null)
    setMessages([])
    setRunning(false)
    setStatus('新しい部屋を作成してください。')
  }

  const updateDraftAgent = (agentId: string, update: Partial<Agent>) => {
    setDraft((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        agents: prev.agents.map((agent) => {
          if (agent.agent_id !== agentId) return agent
          return { ...agent, ...update }
        }),
      }
    })
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">LLM CHAT ROOM</p>
        <h1>モデル同士の会話を楽しむルーム</h1>
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

            <div className="member-strip">
              {room.agents.map((agent) => (
                <span key={agent.agent_id} className="member-pill">
                  {agent.display_name}
                </span>
              ))}
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
                placeholder="途中で話を振るときに入力"
              />
              <button className="primary" type="submit">
                送信
              </button>
            </form>
          </article>

          <aside className="setup-panel">
            <h2>開始前セットアップ</h2>
            <p className="setup-note">会話中は編集できません。</p>
            {draft && (
              <>
                <label className="field">
                  <span>お題</span>
                  <textarea
                    value={draft.subject}
                    onChange={(event) =>
                      setDraft((prev) => (prev ? { ...prev, subject: event.target.value } : prev))
                    }
                    rows={2}
                    disabled={running}
                  />
                </label>
                <div className="agent-editor-list">
                  {draft.agents.map((agent) => (
                    <section key={agent.agent_id} className="agent-editor">
                      <h3>{agent.display_name}</h3>
                      <p className="model">{agent.model}</p>
                      <label className="field">
                        <span>役割</span>
                        <select
                          aria-label={`${agent.display_name} 役割`}
                          value={agent.role_type}
                          onChange={(event) =>
                            updateDraftAgent(agent.agent_id, {
                              role_type: event.target.value as RoleType,
                            })
                          }
                          disabled={running}
                        >
                          <option value="facilitator">ファシリテーター</option>
                          <option value="character">キャラクター</option>
                        </select>
                      </label>
                      {agent.role_type === 'character' && (
                        <label className="field">
                          <span>キャラクター設定</span>
                          <textarea
                            aria-label={`${agent.display_name} キャラクター設定`}
                            value={agent.character_profile}
                            onChange={(event) =>
                              updateDraftAgent(agent.agent_id, {
                                character_profile: event.target.value,
                              })
                            }
                            rows={3}
                            disabled={running}
                          />
                        </label>
                      )}
                    </section>
                  ))}
                </div>
                <button className="primary" onClick={saveSetup} disabled={running}>
                  セットアップを保存
                </button>
              </>
            )}
          </aside>
        </section>
      )}
    </main>
  )
}

export default App

