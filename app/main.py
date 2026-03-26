"""FastAPI アプリケーション本体"""
import hashlib
import hmac
import base64
import json
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
from dotenv import load_dotenv

from app.line_handler import handle_text

load_dotenv()

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

app = FastAPI(title="LINE 割り勘Bot")


def verify_signature(body: bytes, signature: str) -> bool:
    """LINE Webhook のシグネチャを検証する"""
    hash_ = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def reply_message(reply_token: str, text: str) -> None:
    """LINE Reply API でメッセージを送信する"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(LINE_REPLY_URL, json=payload, headers=headers)
        resp.raise_for_status()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        text: str = message.get("text", "")
        reply_token: str = event.get("replyToken", "")

        # グループ/ルーム/個人チャット両対応
        source = event.get("source", {})
        group_id: str = (
            source.get("groupId")
            or source.get("roomId")
            or source.get("userId", "default")
        )

        response_text = handle_text(text, group_id)
        await reply_message(reply_token, response_text)

    return JSONResponse({"status": "ok"})
