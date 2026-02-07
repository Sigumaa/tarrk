# LLM Chat Room (MVP)

複数LLMを同じルームに参加させて、ランダム発話で会話させるローカル向けMVPです。

## 構成

- `backend`: FastAPI + OpenRouter API + WebSocket
- `frontend`: React + Vite + TypeScript

## 前提

- Python (3.13+)
- Node.js (22+)
- OpenRouter APIキー

## Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

`.env` で環境変数を管理できます（`backend/.env` またはリポジトリ直下 `.env`）。

```bash
cp .env.example .env
```

検証:

```bash
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

必要なら API URL を変更:

```bash
# リポジトリ直下 .env
VITE_API_BASE_URL=http://localhost:8000
```

検証:

```bash
npm run test -- --run
npm run lint
npm run build
```

## 使い方

1. テーマと参加モデルを選んで部屋を作成
2. `開始` を押して LLM 同士の会話を開始
3. 入力欄から割り込みメッセージを投稿
4. `停止` または `リセット` で終了
