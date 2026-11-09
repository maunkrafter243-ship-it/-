import asyncio
import base64
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

APP_TITLE = "Discord Bot Manager"
DB_PATH = Path("bots.db")
DATA_DIR = Path("bots")
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title=APP_TITLE)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


DB = get_db()
DB.execute(
    """
    CREATE TABLE IF NOT EXISTS bots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        token TEXT NOT NULL,
        prefix TEXT NOT NULL DEFAULT '!',
        channel_id TEXT DEFAULT ''
    )
    """
)
DB.commit()


@dataclass
class BotRuntime:
    bot_id: int
    task: asyncio.Task
    bot: commands.Bot


RUNTIME: Dict[int, BotRuntime] = {}


def html_page(body: str, title: str = APP_TITLE) -> HTMLResponse:
    return HTMLResponse(
        f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100">
  <div class="mx-auto max-w-6xl px-4 py-8">
    {body}
  </div>
</body>
</html>
"""
    )


def make_prompt(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    return (
        "Ты помощник для Discord-канала. Перепиши текст красиво, коротко и по-русски. "
        "Сохрани смысл. Добавь эмодзи умеренно. Сделай готовый пост для отправки в канал. Текст: "
        + raw
    )


def local_ai_transform(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    header = "🚀 **Обновление**"
    lines = [x.strip() for x in text.replace("\r", "\n").split("\n") if x.strip()]
    if len(lines) == 1:
        lines = [lines[0]]
    bullets = "\n".join(f"• {line}" for line in lines[:8])
    return f"{header}\n\n{bullets}\n\nСпасибо, что вы с нами 💙"


async def create_discord_bot(bot_id: int, token: str, prefix: str) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix=prefix, intents=intents)

    @bot.event
    async def on_ready():
        print(f"[bot {bot_id}] logged in as {bot.user}")

    @bot.command(name="ping")
    async def ping(ctx: commands.Context):
        await ctx.send("Pong!")

    @bot.command(name="news")
    async def news(ctx: commands.Context, *, text: str):
        post = local_ai_transform(text)
        await ctx.send(post)

    return bot


async def run_bot(bot_id: int, token: str, prefix: str):
    bot = await create_discord_bot(bot_id, token, prefix)
    RUNTIME[bot_id] = BotRuntime(bot_id=bot_id, task=asyncio.current_task(), bot=bot)
    try:
        await bot.start(token)
    finally:
        RUNTIME.pop(bot_id, None)


@app.get("/", response_class=HTMLResponse)
def index():
    rows = DB.execute("SELECT * FROM bots ORDER BY id DESC").fetchall()
    cards = []
    for row in rows:
        running = "запущен" if row["id"] in RUNTIME else "остановлен"
        cards.append(
            f"""
            <div class="rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-xl">
              <div class="flex items-start justify-between gap-4">
                <div>
                  <h2 class="text-xl font-semibold">{row['name']}</h2>
                  <p class="mt-1 text-sm text-slate-400">Prefix: <span class="text-slate-200">{row['prefix']}</span> · Канал: <span class="text-slate-200">{row['channel_id'] or 'не задан'}</span></p>
                  <p class="mt-2 text-sm">Статус: <span class="font-semibold text-emerald-400">{running}</span></p>
                </div>
                <div class="flex gap-2">
                  <a class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium hover:bg-emerald-500" href="/start/{row['id']}">Старт</a>
                  <a class="rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium hover:bg-rose-500" href="/stop/{row['id']}">Стоп</a>
                  <a class="rounded-xl bg-slate-700 px-4 py-2 text-sm font-medium hover:bg-slate-600" href="/delete/{row['id']}">Удалить</a>
                </div>
              </div>
            </div>
            """
        )

    return html_page(
        f"""
        <div class="mb-8 rounded-3xl border border-slate-800 bg-gradient-to-r from-slate-900 to-slate-800 p-8 shadow-2xl">
          <h1 class="text-3xl font-bold">{APP_TITLE}</h1>
          <p class="mt-2 max-w-3xl text-slate-300">Минимальная панель для запуска Discord-ботов, отправки красивых новостей и быстрой работы в одном файле.</p>
        </div>

        <div class="grid gap-8 lg:grid-cols-[420px_1fr]">
          <div class="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 class="text-xl font-semibold">Добавить бота</h2>
            <form class="mt-4 space-y-3" method="post" action="/create">
              <input class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none" name="name" placeholder="Название" required>
              <input class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none" name="token" placeholder="Discord токен" required>
              <input class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none" name="prefix" placeholder="Prefix, например !" value="!">
              <input class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none" name="channel_id" placeholder="Channel ID для новостей (необязательно)">
              <button class="w-full rounded-xl bg-indigo-600 px-4 py-3 font-semibold hover:bg-indigo-500">Сохранить</button>
            </form>
          </div>

          <div class="space-y-4">
            <div class="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <h2 class="text-xl font-semibold">AI-новость</h2>
              <form class="mt-4 space-y-3" method="post" action="/ai-preview">
                <textarea class="min-h-36 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none" name="text" placeholder="Напиши черновик новости"></textarea>
                <button class="rounded-xl bg-fuchsia-600 px-4 py-3 font-semibold hover:bg-fuchsia-500">Сгенерировать</button>
              </form>
            </div>
            <div class="space-y-4">
              {''.join(cards) if cards else '<div class="rounded-2xl border border-dashed border-slate-700 bg-slate-900 p-8 text-slate-400">Пока нет ботов</div>'}
            </div>
          </div>
        </div>
        """
    )


@app.post("/create")
def create_bot(
    name: str = Form(...),
    token: str = Form(...),
    prefix: str = Form("!"),
    channel_id: str = Form(""),
):
    try:
        DB.execute(
            "INSERT INTO bots(name, token, prefix, channel_id) VALUES (?, ?, ?, ?)",
            (name.strip(), token.strip(), prefix.strip() or "!", channel_id.strip()),
        )
        DB.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Bot with this name already exists")
    return RedirectResponse("/", status_code=303)


@app.get("/start/{bot_id}")
async def start_bot(bot_id: int):
    row = DB.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot_id in RUNTIME:
        return RedirectResponse("/", status_code=303)
    asyncio.create_task(run_bot(bot_id, row["token"], row["prefix"]))
    return RedirectResponse("/", status_code=303)


@app.get("/stop/{bot_id}")
def stop_bot(bot_id: int):
    runtime = RUNTIME.get(bot_id)
    if runtime:
        runtime.task.cancel()
    return RedirectResponse("/", status_code=303)


@app.get("/delete/{bot_id}")
def delete_bot(bot_id: int):
    runtime = RUNTIME.get(bot_id)
    if runtime:
        runtime.task.cancel()
    DB.execute("DELETE FROM bots WHERE id=?", (bot_id,))
    DB.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/ai-preview", response_class=HTMLResponse)
def ai_preview(text: str = Form(...)):
    post = local_ai_transform(text)
    return html_page(
        f"""
        <div class="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <a class="text-sm text-slate-400 underline" href="/">← Назад</a>
          <h1 class="mt-4 text-2xl font-bold">Предпросмотр</h1>
          <pre class="mt-4 whitespace-pre-wrap rounded-2xl bg-slate-950 p-5 text-slate-100">{post}</pre>
        </div>
        """
    )


@app.post("/api/news/send")
async def send_news(bot_name: str = Form(...), text: str = Form(...)):
    row = DB.execute("SELECT * FROM bots WHERE name=?", (bot_name,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Bot not found")
    if row["id"] not in RUNTIME:
        raise HTTPException(status_code=400, detail="Bot is not running")
    if not row["channel_id"]:
        raise HTTPException(status_code=400, detail="Channel ID is not configured")

    runtime = RUNTIME[row["id"]]
    channel = runtime.bot.get_channel(int(row["channel_id"]))
    if channel is None:
        channel = await runtime.bot.fetch_channel(int(row["channel_id"]))
    post = local_ai_transform(text)
    await channel.send(post)
    return JSONResponse({"ok": True, "sent": post})


@app.get("/health")
def health():
    return {"ok": True, "running_bots": list(RUNTIME.keys())}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
