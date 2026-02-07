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

  it('renders newly added model options', () => {
    render(<App />)

    expect(screen.getByText('moonshotai/kimi-k2.5')).toBeInTheDocument()
    expect(screen.getByText('google/gemini-3-flash-preview')).toBeInTheDocument()
    expect(screen.getByText('anthropic/claude-sonnet-4.5')).toBeInTheDocument()
    expect(screen.getByText('x-ai/grok-4.1-fast')).toBeInTheDocument()
  })

  it('creates room and renders websocket messages', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-1',
          topic: 'おにぎり議論',
          background: '背景',
          context: '文脈',
          language: '日本語',
          global_instruction: '短く議論する',
          personas: [
            {
              agent_id: 'agent-1',
              model: 'openai/gpt-4o-mini',
              role_name: 'ファシリテーター',
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

  it('allows updating instructions before start', async () => {
    const mockedFetch = vi.mocked(fetch)
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          room_id: 'room-2',
          topic: '初期テーマ',
          background: '初期背景',
          context: '初期文脈',
          language: '日本語',
          global_instruction: '初期指示',
          personas: [
            {
              agent_id: 'agent-1',
              model: 'moonshotai/kimi-k2.5',
              role_name: '検証担当',
              persona_prompt: '初期persona',
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
          topic: '更新テーマ',
          background: '更新背景',
          context: '更新文脈',
          language: '日本語',
          global_instruction: '更新した全体指示',
          personas: [
            {
              agent_id: 'agent-1',
              model: 'moonshotai/kimi-k2.5',
              role_name: '検証担当',
              persona_prompt: '更新persona',
            },
          ],
        }),
        { status: 200 },
      ),
    )

    render(<App />)

    await userEvent.type(screen.getByPlaceholderText('例: 最高の深夜メシは何か'), '初期テーマ')
    await userEvent.click(screen.getByRole('button', { name: '部屋を作る' }))
    expect(await screen.findByText('Room: room-2')).toBeInTheDocument()

    const themeInput = screen.getByLabelText('会話テーマ')
    await userEvent.clear(themeInput)
    await userEvent.type(themeInput, '更新テーマ')

    const globalInstructionInput = screen.getByLabelText('全体システム指示')
    await userEvent.clear(globalInstructionInput)
    await userEvent.type(globalInstructionInput, '更新した全体指示')

    const personaInput = screen.getByLabelText('agent-1 (検証担当)')
    await userEvent.clear(personaInput)
    await userEvent.type(personaInput, '更新persona')

    await userEvent.click(screen.getByRole('button', { name: '指示を保存' }))
    expect(await screen.findByText('指示文を保存しました。')).toBeInTheDocument()

    const calls = mockedFetch.mock.calls
    const updateCall = calls.find((call) => String(call[0]).includes('/instructions'))
    expect(updateCall).toBeDefined()
    const init = updateCall?.[1] as RequestInit
    const body = JSON.parse(String(init.body)) as {
      topic: string
      global_instruction: string
      personas: Array<{ agent_id: string; persona_prompt: string }>
    }
    expect(body.topic).toBe('更新テーマ')
    expect(body.global_instruction).toBe('更新した全体指示')
    expect(body.personas[0]).toEqual({
      agent_id: 'agent-1',
      persona_prompt: '更新persona',
    })
  })
})

