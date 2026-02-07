import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

class MockWebSocket {
  static instances: MockWebSocket[] = []

  readonly url: string
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  open(): void {
    this.onopen?.(new Event('open'))
  }

  close(): void {
    this.onclose?.(new CloseEvent('close'))
  }

  emit(event: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(event) }))
  }
}

describe('App', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('fetch', vi.fn())
  })

  it('shows validation when subject is empty', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))

    expect(await screen.findByText('議論したいお題を入力してください。')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('renders model presets', () => {
    render(<App />)

    expect(screen.getByText('moonshotai/kimi-k2.5')).toBeInTheDocument()
    expect(screen.getByText('deepseek/deepseek-v3.2')).toBeInTheDocument()
    expect(screen.getByText('minimax/minimax-m2.1')).toBeInTheDocument()
    expect(screen.getByText('arcee-ai/trinity-large-preview:free')).toBeInTheDocument()
    expect(screen.getByText('z-ai/glm-4.7')).toBeInTheDocument()
    expect(screen.getByText('google/gemini-3-flash-preview')).toBeInTheDocument()
    expect(screen.getByText('anthropic/claude-sonnet-4.5')).toBeInTheDocument()
    expect(screen.getByText('x-ai/grok-4.1-fast')).toBeInTheDocument()
    expect(screen.queryByText('google/gemini-2.0-flash')).not.toBeInTheDocument()
  })

  it('creates room and renders websocket messages with model display names', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-1',
          subject: 'おにぎり議論',
          conversation_mode: 'philosophy_debate',
          global_instruction: '',
          turn_interval_seconds: 0.5,
          agents: [
            {
              agent_id: 'agent-1',
              model: 'openai/gpt-4o-mini',
              display_name: 'openai/gpt-4o-mini',
              role_type: 'facilitator',
              character_profile: '',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      'おにぎり議論',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))

    expect(await screen.findByText('Room: room-1')).toBeInTheDocument()
    expect(screen.getAllByText('openai/gpt-4o-mini').length).toBeGreaterThan(0)
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.instances[0].open()
      MockWebSocket.instances[0].emit({
        type: 'message',
        payload: {
          role: 'agent',
          speaker_id: 'openai/gpt-4o-mini',
          content: 'しかし、コスト面は再検討が必要です。',
          timestamp: '2026-01-01T00:00:00Z',
        },
      })
    })

    expect((await screen.findAllByText('しかし、コスト面は再検討が必要です。')).length).toBeGreaterThan(
      0,
    )
    expect(screen.getByText('幕: 導入')).toBeInTheDocument()

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/room/create'),
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('updates act and round badges from room_state', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-2',
          subject: '検証テーマ',
          conversation_mode: 'philosophy_debate',
          global_instruction: '',
          turn_interval_seconds: 0.5,
          agents: [
            {
              agent_id: 'agent-1',
              model: 'm1',
              display_name: 'm1',
              role_type: 'facilitator',
              character_profile: '',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      '検証テーマ',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-2')).toBeInTheDocument()

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'room_state',
        payload: {
          running: true,
          current_act: '具体化',
          rounds_completed: 7,
        },
      })
    })

    expect(await screen.findByText('幕: 具体化')).toBeInTheDocument()
    expect(await screen.findByText('発話: 7')).toBeInTheDocument()
  })

  it('renders generation logs and updates status while requesting model calls', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-3',
          subject: 'ログ検証',
          conversation_mode: 'philosophy_debate',
          global_instruction: '',
          turn_interval_seconds: 0.5,
          agents: [
            {
              agent_id: 'agent-1',
              model: 'm1',
              display_name: 'm1',
              role_type: 'facilitator',
              character_profile: '',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      'ログ検証',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-3')).toBeInTheDocument()

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'generation_log',
        payload: {
          round_index: 3,
          model: 'm1',
          display_name: 'm1',
          act: '具体化',
          status: 'requesting',
          detail: '',
          timestamp: '2026-01-01T00:02:00Z',
        },
      })
    })

    expect(await screen.findByText('アクセス中: m1 (具体化)')).toBeInTheDocument()
    expect(await screen.findByText('R3 requesting m1')).toBeInTheDocument()

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'generation_log',
        payload: {
          round_index: 3,
          model: 'm1',
          display_name: 'm1',
          act: '具体化',
          status: 'failed',
          detail: 'OpenRouter API error',
          timestamp: '2026-01-01T00:02:03Z',
        },
      })
    })

    expect(await screen.findByText('呼び出し失敗: m1')).toBeInTheDocument()
    expect(await screen.findByText('幕: 具体化 / OpenRouter API error')).toBeInTheDocument()
  })

  it('applies a consistent speaker accent across member card, message, and access log', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-3b',
          subject: '配色確認',
          conversation_mode: 'philosophy_debate',
          global_instruction: '',
          turn_interval_seconds: 0.5,
          agents: [
            {
              agent_id: 'agent-1',
              model: 'x-ai/grok-4.1-fast',
              display_name: 'x-ai/grok-4.1-fast',
              role_type: 'facilitator',
              character_profile: '',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      '配色確認',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-3b')).toBeInTheDocument()

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'message',
        payload: {
          role: 'agent',
          speaker_id: 'x-ai/grok-4.1-fast',
          content: '観察可能な現象として定義から始めましょう。',
          timestamp: '2026-01-01T00:03:00Z',
        },
      })
      MockWebSocket.instances[0].emit({
        type: 'generation_log',
        payload: {
          round_index: 2,
          model: 'x-ai/grok-4.1-fast',
          display_name: 'x-ai/grok-4.1-fast',
          act: '導入',
          status: 'requesting',
          detail: '',
          timestamp: '2026-01-01T00:03:02Z',
        },
      })
    })

    const membersSection = screen.getByRole('heading', { name: '参加モデル' }).closest('section')
    expect(membersSection).toHaveClass('members-section')

    const memberItem = membersSection?.querySelector('.member-item') as HTMLElement | null
    expect(memberItem).not.toBeNull()
    const memberAccent = memberItem?.style.getPropertyValue('--speaker-accent') ?? ''
    expect(memberAccent).not.toBe('')

    const messageItem = screen.getByText('観察可能な現象として定義から始めましょう。')
      .closest('.msg-agent') as HTMLElement | null
    expect(messageItem).not.toBeNull()
    expect(messageItem?.style.getPropertyValue('--speaker-accent')).toBe(memberAccent)

    const logItem = screen.getByText('R2 requesting x-ai/grok-4.1-fast')
      .closest('.log-item') as HTMLElement | null
    expect(logItem).not.toBeNull()
    expect(logItem?.style.getPropertyValue('--speaker-accent')).toBe(memberAccent)
  })

  it('calls conclude endpoint when user clicks the conclude button', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            room_id: 'room-4',
            subject: '結論判断',
            conversation_mode: 'philosophy_debate',
            global_instruction: '',
            turn_interval_seconds: 0.5,
            agents: [
              {
                agent_id: 'agent-1',
                model: 'm1',
                display_name: 'm1',
                role_type: 'facilitator',
                character_profile: '',
              },
            ],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'concluded' }), { status: 200 }))

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      '結論判断',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-4')).toBeInTheDocument()

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'room_state',
        payload: {
          running: true,
          current_act: '衝突',
          rounds_completed: 4,
        },
      })
    })

    await userEvent.click(screen.getByRole('button', { name: '発展なしで終了' }))

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/room/room-4/conclude'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('applies conversation config before start', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            room_id: 'room-5',
            subject: '自由意志',
            conversation_mode: 'philosophy_debate',
            global_instruction: '',
            turn_interval_seconds: 0.5,
            agents: [
              {
                agent_id: 'agent-1',
                model: 'm1',
                display_name: 'm1',
                role_type: 'facilitator',
                character_profile: '',
              },
            ],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            room_id: 'room-5',
            subject: '自由意志',
            conversation_mode: 'consensus_lab',
            global_instruction: '倫理面を優先する',
            turn_interval_seconds: 0.2,
            agents: [
              {
                agent_id: 'agent-1',
                model: 'm1',
                display_name: 'm1',
                role_type: 'facilitator',
                character_profile: '',
              },
            ],
          }),
          { status: 200 },
        ),
      )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      '自由意志',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))

    expect(await screen.findByText('Room: room-5')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByDisplayValue('哲学討論'), 'consensus_lab')
    await userEvent.clear(screen.getByPlaceholderText('開始前なら自由に調整できます'))
    await userEvent.type(screen.getByPlaceholderText('開始前なら自由に調整できます'), '倫理面を優先する')
    await userEvent.selectOptions(screen.getAllByRole('combobox')[1], '0.2')

    await userEvent.click(screen.getByRole('button', { name: '会話設定を反映' }))

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/room/room-5/config'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('consensus_lab'),
        }),
      )
    })
  })

  it('supports theater toggle and message pinning', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-6',
          subject: '価値観の衝突',
          conversation_mode: 'philosophy_debate',
          global_instruction: '',
          turn_interval_seconds: 0.5,
          agents: [
            {
              agent_id: 'agent-1',
              model: 'm1',
              display_name: 'm1',
              role_type: 'facilitator',
              character_profile: '',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 自由意志は幻想か、それとも実在するか'),
      '価値観の衝突',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-6')).toBeInTheDocument()

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'message',
        payload: {
          role: 'agent',
          speaker_id: 'm1',
          content: 'この主張は価値基準の定義を先に置くべきです。',
          timestamp: '2026-01-01T00:05:00Z',
        },
      })
    })

    const layout = screen.getByText('Room: room-6').closest('section')
    await userEvent.click(screen.getByRole('button', { name: 'シアター' }))
    expect(layout?.className).toContain('theater-mode')

    await userEvent.click(screen.getByRole('button', { name: 'ピン' }))
    const pinnedTexts = await screen.findAllByText('この主張は価値基準の定義を先に置くべきです。')
    expect(pinnedTexts.length).toBeGreaterThanOrEqual(2)
  })
})
