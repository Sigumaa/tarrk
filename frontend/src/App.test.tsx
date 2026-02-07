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
    expect(screen.getByText('google/gemini-3-flash-preview')).toBeInTheDocument()
    expect(screen.getByText('anthropic/claude-sonnet-4.5')).toBeInTheDocument()
    expect(screen.getByText('x-ai/grok-4.1-fast')).toBeInTheDocument()
  })

  it('creates room and renders websocket messages with model display names', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-1',
          subject: 'おにぎり議論',
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
      screen.getByPlaceholderText('例: 1時間で作れる面白いWebサービス案を考える'),
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
      MockWebSocket.instances[0].emit({
        type: 'message',
        payload: {
          role: 'agent',
          speaker_id: 'openai/gpt-4o-mini',
          content: '結論として、この方向で進めます。',
          timestamp: '2026-01-01T00:01:00Z',
        },
      })
    })

    expect((await screen.findAllByText('しかし、コスト面は再検討が必要です。')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('結論として、この方向で進めます。')).length).toBeGreaterThan(0)
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
      screen.getByPlaceholderText('例: 1時間で作れる面白いWebサービス案を考える'),
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
})
