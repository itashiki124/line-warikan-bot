"""FastAPI アプリケーション本体"""
import hashlib
import hmac
import base64
import json
import logging
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
from dotenv import load_dotenv

from app.line_handler import handle_text

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

app = FastAPI(title="LINE 割り勘Bot")


def _line_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


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
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(LINE_REPLY_URL, json=payload, headers=_line_headers())
        logger.info("LINE Reply API: status=%d body=%s", resp.status_code, resp.text)
        resp.raise_for_status()


async def push_message(to: str, text: str) -> None:
    """LINE Push API でメッセージを送信する (Reply失敗時のフォールバック)"""
    payload = {
        "to": to,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(LINE_PUSH_URL, json=payload, headers=_line_headers())
        logger.info("LINE Push API: status=%d body=%s", resp.status_code, resp.text)
        resp.raise_for_status()


def _get_reply_target(source: dict) -> str:
    """Push API 用の送信先IDを取得する"""
    return (
        source.get("groupId")
        or source.get("roomId")
        or source.get("userId", "")
    )


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        logger.warning("Invalid signature received")
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)
    logger.info("Webhook received: %d events", len(data.get("events", [])))

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

        logger.info("Processing message: %r from group %s", text, group_id)
        try:
            response_text = handle_text(text, group_id)
        except Exception as e:
            logger.error("Failed to handle message: %s", e, exc_info=True)
            response_text = "エラーが発生しました。もう一度お試しください。"

        # Reply API で送信、失敗時は Push API にフォールバック
        try:
            await reply_message(reply_token, response_text)
            logger.info("Reply sent successfully")
        except Exception as e:
            logger.warning("Reply API failed: %s — falling back to Push API", e)
            try:
                push_to = _get_reply_target(source)
                if push_to:
                    await push_message(push_to, response_text)
                    logger.info("Push message sent successfully")
                else:
                    logger.error("No push target available")
            except Exception as e2:
                logger.error("Push API also failed: %s", e2, exc_info=True)

    return JSONResponse({"status": "ok"})
