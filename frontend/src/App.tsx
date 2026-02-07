import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type MessageRole = 'user' | 'agent'
type RoleType = 'facilitator' | 'character'
type ConversationMode = 'philosophy_debate' | 'devils_advocate' | 'consensus_lab'
type DensityMode = 'standard' | 'compact'

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
  conversation_mode?: ConversationMode
  global_instruction?: string
  turn_interval_seconds?: number
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
  conversation_mode?: ConversationMode
  global_instruction?: string
  turn_interval_seconds?: number
  agents: Agent[]
  messages: ChatMessage[]
}

type SocketEvent = {
  type: 'room_snapshot' | 'room_state' | 'message' | 'generation_log' | 'error'
  payload: unknown
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

type SpeedOption = {
  label: string
  value: number
}

const MODEL_OPTIONS = [
  'openai/gpt-4o-mini',
  'moonshotai/kimi-k2.5',
  'google/gemini-3-flash-preview',
  'anthropic/claude-sonnet-4.5',
  'x-ai/grok-4.1-fast',
  'meta-llama/llama-3.3-70b-instruct',
]

const MODE_OPTIONS: Array<{ value: ConversationMode; label: string; description: string }> = [
  {
    value: 'philosophy_debate',
    label: '哲学討論',
    description: '定義と価値判断を掘り下げる会話',
  },
  {
    value: 'devils_advocate',
    label: '悪魔の代弁者',
    description: '反証と失敗シナリオを重視する会話',
  },
  {
    value: 'consensus_lab',
    label: '合意形成ラボ',
    description: '対立を残しつつ実行可能な合意を作る会話',
  },
]

const SPEED_OPTIONS: SpeedOption[] = [
  { label: 'ゆっくり', value: 1.0 },
  { label: '標準', value: 0.5 },
  { label: '速い', value: 0.2 },
  { label: '超速', value: 0.08 },
]

const END_REASON_LABEL: Record<string, string> = {
  max_rounds: 'ラウンド上限に到達',
  manual_stop: '手動停止',
  user_concluded: '発展なしで終了',
  failures: '連続エラー',
}

function speedLabel(value: number): string {
  const matched = SPEED_OPTIONS.find((item) => Math.abs(item.value - value) < 1e-6)
  if (matched) {
    return matched.label
  }
  return `${value.toFixed(2)}秒`
}

function modeLabel(mode: ConversationMode): string {
  return MODE_OPTIONS.find((item) => item.value === mode)?.label ?? mode
}

function messageKey(message: ChatMessage, index: number): string {
  return `${message.timestamp}-${index}`
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
  const [conversationMode, setConversationMode] = useState<ConversationMode>('philosophy_debate')
  const [globalInstruction, setGlobalInstruction] = useState('')
  const [turnIntervalSeconds, setTurnIntervalSeconds] = useState(0.5)

  const [room, setRoom] = useState<RoomPayload | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [generationLogs, setGenerationLogs] = useState<GenerationLog[]>([])
  const [pinnedMessageKeys, setPinnedMessageKeys] = useState<string[]>([])
  const [userInput, setUserInput] = useState('')
  const [running, setRunning] = useState(false)
  const [currentAct, setCurrentAct] = useState('導入')
  const [roundsCompleted, setRoundsCompleted] = useState(0)
  const [status, setStatus] = useState('お題を入れて部屋を作成してください。')

  const [densityMode, setDensityMode] = useState<DensityMode>('standard')
  const [theaterMode, setTheaterMode] = useState(false)

  const socketRef = useRef<WebSocket | null>(null)
  const messageListRef = useRef<HTMLUListElement | null>(null)

  const pinnedMessages = useMemo(
    () =>
      messages
        .map((message, index) => ({ key: messageKey(message, index), message }))
        .filter((item) => pinnedMessageKeys.includes(item.key)),
    [messages, pinnedMessageKeys],
  )

  useEffect(() => {
    return () => {
      if (socketRef.current) {
        socketRef.current.close()
      }
    }
  }, [])

  useEffect(() => {
    const list = messageListRef.current
    if (!list) return
    list.scrollTop = list.scrollHeight
  }, [messages])

  const applyRoomPayload = (payload: RoomPayload | SnapshotPayload) => {
    const mode = payload.conversation_mode ?? 'philosophy_debate'
    const interval = payload.turn_interval_seconds ?? 0.5
    setConversationMode(mode)
    setGlobalInstruction(payload.global_instruction ?? '')
    setTurnIntervalSeconds(interval)
    setRoom({
      room_id: payload.room_id,
      subject: payload.subject,
      conversation_mode: mode,
      global_instruction: payload.global_instruction ?? '',
      turn_interval_seconds: interval,
      agents: payload.agents ?? [],
    })
  }

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
        applyRoomPayload(payload)
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
          const reason = END_REASON_LABEL[payload.end_reason] ?? payload.end_reason
          setStatus(`会話終了: ${reason}`)
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
          conversation_mode: conversationMode,
          global_instruction: globalInstruction.trim(),
          turn_interval_seconds: turnIntervalSeconds,
        }),
      })
      applyRoomPayload(payload)
      setMessages([])
      setPinnedMessageKeys([])
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

  const concludeChat = async () => {
    if (!room) return
    try {
      await requestJson<{ status: string }>(`${apiBase}/api/room/${room.room_id}/conclude`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      setStatus('終了要求を送信しました。')
    } catch (error) {
      setStatus(`終了要求に失敗しました: ${String(error)}`)
    }
  }

  const applyRoomConfig = async () => {
    if (!room) return

    const payload: {
      conversation_mode?: ConversationMode
      global_instruction?: string
      turn_interval_seconds?: number
    } = {
      turn_interval_seconds: turnIntervalSeconds,
    }

    if (!running) {
      payload.conversation_mode = conversationMode
      payload.global_instruction = globalInstruction.trim()
    }

    try {
      const updated = await requestJson<RoomPayload>(`${apiBase}/api/room/${room.room_id}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      applyRoomPayload(updated)
      setStatus(running ? '速度設定を反映しました。' : '会話設定を反映しました。')
    } catch (error) {
      setStatus(`設定反映に失敗しました: ${String(error)}`)
    }
  }

  const applySpeed = async (next: number) => {
    if (!room) return
    try {
      const updated = await requestJson<RoomPayload>(`${apiBase}/api/room/${room.room_id}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turn_interval_seconds: next }),
      })
      applyRoomPayload(updated)
      setStatus(`会話速度を ${speedLabel(next)} に変更しました。`)
    } catch (error) {
      setStatus(`速度変更に失敗しました: ${String(error)}`)
    }
  }

  const onChangeSpeed = (value: number) => {
    setTurnIntervalSeconds(value)
    void applySpeed(value)
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

  const togglePinnedMessage = (key: string) => {
    setPinnedMessageKeys((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key],
    )
  }

  const resetRoom = () => {
    if (socketRef.current) {
      socketRef.current.close()
      socketRef.current = null
    }
    setRoom(null)
    setMessages([])
    setPinnedMessageKeys([])
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
              placeholder="例: 自由意志は幻想か、それとも実在するか"
              rows={3}
            />
          </label>

          <div className="field">
            <span>会話モード</span>
            <select
              value={conversationMode}
              onChange={(event) => setConversationMode(event.target.value as ConversationMode)}
            >
              {MODE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="field-help">
              {MODE_OPTIONS.find((option) => option.value === conversationMode)?.description}
            </p>
          </div>

          <label className="field">
            <span>全体指示（任意）</span>
            <textarea
              value={globalInstruction}
              onChange={(event) => setGlobalInstruction(event.target.value)}
              placeholder="例: 具体例を必ず含める。倫理と長期影響を優先する。"
              rows={3}
            />
          </label>

          <div className="field speed-row">
            <span>会話速度</span>
            <select
              value={turnIntervalSeconds}
              onChange={(event) => setTurnIntervalSeconds(Number(event.target.value))}
            >
              {SPEED_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

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
        <section className={`room-layout ${theaterMode ? 'theater-mode' : ''}`}>
          <article className="chat-panel">
            <div className="toolbar">
              <div className="toolbar-main">
                <strong>Room: {room.room_id}</strong>
                <p className="subject-line">お題: {room.subject}</p>
              </div>
              <div className="toolbar-badges">
                <span className="act-badge">幕: {currentAct}</span>
                <span className="act-badge">発話: {roundsCompleted}</span>
                <span className="act-badge">モード: {modeLabel(conversationMode)}</span>
                <span className="act-badge">速度: {speedLabel(turnIntervalSeconds)}</span>
              </div>
              <div className="toolbar-buttons">
                <button className="primary" onClick={startChat} disabled={running}>
                  開始
                </button>
                <button onClick={concludeChat} disabled={!running}>
                  発展なしで終了
                </button>
                <button onClick={() => setTheaterMode((prev) => !prev)}>
                  {theaterMode ? '通常表示' : 'シアター'}
                </button>
                <button onClick={resetRoom}>リセット</button>
              </div>
            </div>

            <div className="display-controls">
              <label className="compact-control">
                表示密度
                <select
                  value={densityMode}
                  onChange={(event) => setDensityMode(event.target.value as DensityMode)}
                >
                  <option value="standard">標準</option>
                  <option value="compact">コンパクト</option>
                </select>
              </label>

              <label className="compact-control">
                速度
                <select
                  value={turnIntervalSeconds}
                  onChange={(event) => onChangeSpeed(Number(event.target.value))}
                >
                  {SPEED_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <ul className={`message-list density-${densityMode}`} ref={messageListRef}>
              {messages.length === 0 ? (
                <li className="empty">会話はまだありません。開始してみましょう。</li>
              ) : (
                messages.map((message, index) => {
                  const key = messageKey(message, index)
                  const pinned = pinnedMessageKeys.includes(key)
                  return (
                    <li
                      key={key}
                      className={`msg msg-${message.role} ${
                        message.speaker_id === '総括' ? 'msg-summary' : ''
                      } ${message.speaker_id === 'お題カード' ? 'msg-card' : ''}`}
                    >
                      <div className="msg-head">
                        <p className="meta">{message.speaker_id}</p>
                        <button
                          className={`pin-button ${pinned ? 'active' : ''}`}
                          onClick={() => togglePinnedMessage(key)}
                          type="button"
                        >
                          {pinned ? '固定解除' : 'ピン'}
                        </button>
                      </div>
                      <p>{message.content}</p>
                    </li>
                  )
                })
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
            <section className="config-panel">
              <h2>会話設定</h2>
              <label className="field compact-field">
                <span>会話モード</span>
                <select
                  disabled={running}
                  value={conversationMode}
                  onChange={(event) => setConversationMode(event.target.value as ConversationMode)}
                >
                  {MODE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field compact-field">
                <span>全体指示</span>
                <textarea
                  disabled={running}
                  value={globalInstruction}
                  onChange={(event) => setGlobalInstruction(event.target.value)}
                  rows={4}
                  placeholder="開始前なら自由に調整できます"
                />
              </label>
              <button className="primary" onClick={applyRoomConfig}>
                {running ? '速度のみ反映' : '会話設定を反映'}
              </button>
            </section>

            <section className="pins-panel">
              <h3>ピン留め</h3>
              <ul className="pins-list">
                {pinnedMessages.length === 0 ? (
                  <li className="log-empty">ピン留めはまだありません。</li>
                ) : (
                  pinnedMessages.map((item) => (
                    <li key={`pin-${item.key}`} className="pin-item">
                      <p className="pin-speaker">{item.message.speaker_id}</p>
                      <p className="pin-content">{item.message.content}</p>
                    </li>
                  ))
                )}
              </ul>
            </section>

            <section>
              <h3>参加モデル</h3>
              <p className="members-note">
                役割は自動設定です（ファシリテーター1名 + お題依存キャラクター）。
              </p>
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
            </section>

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
