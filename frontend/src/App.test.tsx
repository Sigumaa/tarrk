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

  it('creates room and renders websocket messages with model display name', async () => {
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
              persona_prompt: '司会',
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
          content: 'こんにちは',
          timestamp: '2026-01-01T00:00:00Z',
        },
      })
    })

    expect(await screen.findByText('こんにちは')).toBeInTheDocument()
    expect((await screen.findAllByText('openai/gpt-4o-mini')).length).toBeGreaterThan(0)

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/room/create'),
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('saves pre-start setup with role selection', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-2',
          subject: '初期お題',
          agents: [
            {
              agent_id: 'agent-1',
              model: 'm1',
              display_name: 'm1',
              role_type: 'facilitator',
              character_profile: '',
              persona_prompt: '司会',
            },
            {
              agent_id: 'agent-2',
              model: 'm2',
              display_name: 'm2',
              role_type: 'character',
              character_profile: '初期キャラ',
              persona_prompt: 'キャラ',
            },
          ],
        }),
        { status: 200 },
      ),
    )
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-2',
          subject: '更新お題',
          agents: [
            {
              agent_id: 'agent-1',
              model: 'm1',
              display_name: 'm1',
              role_type: 'character',
              character_profile: '辛口批評家',
              persona_prompt: 'キャラ',
            },
            {
              agent_id: 'agent-2',
              model: 'm2',
              display_name: 'm2',
              role_type: 'facilitator',
              character_profile: '',
              persona_prompt: '司会',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)
    await userEvent.type(
      screen.getByPlaceholderText('例: 1時間で作れる面白いWebサービス案を考える'),
      '初期お題',
    )
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-2')).toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText('お題'))
    await userEvent.type(screen.getByLabelText('お題'), '更新お題')

    await userEvent.selectOptions(screen.getByLabelText('m1 役割'), 'character')
    await userEvent.type(screen.getByLabelText('m1 キャラクター設定'), '辛口批評家')
    await userEvent.selectOptions(screen.getByLabelText('m2 役割'), 'facilitator')

    await userEvent.click(screen.getByRole('button', { name: 'セットアップを保存' }))
    expect(await screen.findByText('設定を保存しました。')).toBeInTheDocument()

    const updateCall = mockedFetch.mock.calls.find((call) => String(call[0]).includes('/setup'))
    expect(updateCall).toBeDefined()
    const body = JSON.parse(String((updateCall?.[1] as RequestInit).body)) as {
      subject: string
      agents: Array<{ role_type: string }>
    }
    expect(body.subject).toBe('更新お題')
    expect(body.agents[0].role_type).toBe('character')
    expect(body.agents[1].role_type).toBe('facilitator')
  })
})
