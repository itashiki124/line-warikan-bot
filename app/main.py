"""FastAPI アプリケーション本体"""
import hashlib
import hmac
import base64
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from dotenv import load_dotenv

from app.line_handler import handle_text, BotResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数の診断ログ
logger.info("Starting LINE 割り勘Bot...")
logger.info("Python version: %s", sys.version)
logger.info("OPENAI_API_KEY: %s", "SET" if os.environ.get("OPENAI_API_KEY") else "NOT SET")
logger.info("LINE_CHANNEL_SECRET: %s", "SET" if os.environ.get("LINE_CHANNEL_SECRET") else "NOT SET")
logger.info("LINE_CHANNEL_ACCESS_TOKEN: %s", "SET" if os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") else "NOT SET")
logger.info("LIFF_ID: %s", "SET" if os.environ.get("LIFF_ID") else "NOT SET")

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LIFF_ID = os.environ.get("LIFF_ID", "")
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

app = FastAPI(title="LINE 割り勘Bot")

# 静的ファイル配信 (LIFF フォーム用)
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


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


async def reply_message(reply_token: str, response: BotResponse) -> None:
    """LINE Reply API でメッセージを送信する"""
    payload = {
        "replyToken": reply_token,
        "messages": [response.to_line_message()],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(LINE_REPLY_URL, json=payload, headers=_line_headers())
        logger.info("LINE Reply API: status=%d body=%s", resp.status_code, resp.text)
        resp.raise_for_status()


async def push_message(to: str, response: BotResponse) -> None:
    """LINE Push API でメッセージを送信する (Reply失敗時のフォールバック)"""
    payload = {
        "to": to,
        "messages": [response.to_line_message()],
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


def _source_summary(source: dict) -> str:
    """Webhook source をログ出力しやすい短い文字列にする。"""
    source_type = source.get("type", "unknown")
    group_id = source.get("groupId")
    room_id = source.get("roomId")
    user_id = source.get("userId")
    return (
        f"type={source_type} "
        f"group={'yes' if group_id else 'no'} "
        f"room={'yes' if room_id else 'no'} "
        f"user={'yes' if user_id else 'no'}"
    )


@app.get("/health")
async def health() -> JSONResponse:
    from app.ai_parser import _get_api_key
    from app.storage import _persistence_enabled
    return JSONResponse({
        "status": "ok",
        "python": sys.version,
        "ai_enabled": bool(_get_api_key()),
        "liff_enabled": bool(LIFF_ID),
        "persistence_enabled": _persistence_enabled(),
    })


@app.get("/test-ai")
async def test_ai() -> JSONResponse:
    """AI パースの動作確認用エンドポイント"""
    from app.ai_parser import parse_with_ai, _get_api_key
    api_key = _get_api_key()
    if not api_key:
        return JSONResponse({"error": "OPENAI_API_KEY is not set", "key_length": 0})
    try:
        result = await parse_with_ai("ランチ1500円")
        return JSONResponse({
            "model": "gpt-4o-mini",
            "key_length": len(api_key),
            "result": result.__dict__ if result else None,
        })
    except Exception as e:
        return JSONResponse({"error": str(e), "key_length": len(api_key)}, status_code=500)


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        logger.warning("Invalid signature received")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = json.loads(body)
    except Exception as e:
        logger.error("Failed to parse webhook body: %s", e)
        return JSONResponse({"status": "ok"})

    logger.info("Webhook received: %d events", len(data.get("events", [])))

    for event in data.get("events", []):
        event_type = event.get("type")
        source = event.get("source", {})
        logger.info("Webhook event: type=%s source=(%s)", event_type, _source_summary(source))

        if event_type != "message":
            logger.info("Skipping non-message event: %s", event_type)
            continue

        message = event.get("message", {})
        message_type = message.get("type")
        if message_type != "text":
            logger.info("Skipping non-text message: %s source=(%s)", message_type, _source_summary(source))
            continue

        text: str = message.get("text", "")
        reply_token: str = event.get("replyToken", "")
        sender_id: str = source.get("userId", "")

        # グループ/ルーム/個人チャット両対応
        group_id: str = (
            source.get("groupId")
            or source.get("roomId")
            or source.get("userId", "default")
        )

        logger.info(
            "Processing message: %r conversation=%s reply_token=%s source=(%s)",
            text,
            group_id,
            "yes" if reply_token else "no",
            _source_summary(source),
        )
        try:
            response = await handle_text(text, group_id, sender_id=sender_id, liff_id=LIFF_ID)
        except Exception as e:
            logger.error("Failed to handle message: %s", e, exc_info=True)
            response = BotResponse("エラーが発生しました。もう一度お試しください。")

        # Reply API で送信、失敗時は Push API にフォールバック
        try:
            await reply_message(reply_token, response)
            logger.info("Reply sent successfully")
        except Exception as e:
            logger.warning("Reply API failed: %s — falling back to Push API", e)
            try:
                push_to = _get_reply_target(source)
                if push_to:
                    await push_message(push_to, response)
                    logger.info("Push message sent successfully")
                else:
                    logger.error("No push target available")
            except Exception as e2:
                logger.error("Push API also failed: %s", e2, exc_info=True)

    return JSONResponse({"status": "ok"})
