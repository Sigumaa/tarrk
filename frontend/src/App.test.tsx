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

  it('shows validation when topic is empty', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))

    expect(await screen.findByText('テーマを入力してください。')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('creates room and renders websocket messages', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-1',
          topic: 'おにぎり議論',
          personas: [
            {
              agent_id: 'agent-1',
              model: 'openai/gpt-4o-mini',
              persona_prompt: 'test persona',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)

    await userEvent.type(screen.getByPlaceholderText('例: 最高の深夜メシは何か'), 'おにぎり議論')
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))

    expect(await screen.findByText('Room: room-1')).toBeInTheDocument()
    expect(MockWebSocket.instances).toHaveLength(1)
    act(() => {
      MockWebSocket.instances[0].open()
    })

    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'message',
        payload: {
          role: 'agent',
          speaker_id: 'agent-1',
          content: 'こんにちは',
          timestamp: '2026-01-01T00:00:00Z',
        },
      })
    })

    expect(await screen.findByText('こんにちは')).toBeInTheDocument()

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/room/create'),
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })
})
