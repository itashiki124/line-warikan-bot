"""生成AIを使った自然言語メッセージの解釈モジュール

Groq API (無料枠) を使用して、ざっくりしたメッセージから
割り勘に必要な情報を抽出する。
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _get_api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "")

SYSTEM_PROMPT = """\
あなたはLINEグループの割り勘Botのメッセージ解析器です。
ユーザーのメッセージを解析し、以下のいずれかのアクションとして分類してJSON形式で返してください。

## アクション一覧

1. **warikan** - 即時割り勘計算（金額と人数が含まれる）
   {"action": "warikan", "amount": 金額(int), "people": 人数(int)}

2. **record** - 支払い記録（誰かが何かを払った情報）
   {"action": "record", "amount": 金額(int), "label": "説明", "payer": "支払者名 or null"}

3. **members** - メンバー設定
   {"action": "members", "names": ["名前1", "名前2", ...]}

4. **set_people** - 人数設定
   {"action": "set_people", "people": 人数(int)}

5. **settle** - 精算リクエスト
   {"action": "settle"}

6. **reset** - リセット
   {"action": "reset"}

7. **help** - ヘルプ
   {"action": "help"}

8. **status** - 現在の集計状況を確認
   {"action": "status"}

9. **unknown** - 割り勘に関係ない会話（挨拶、雑談など）
   {"action": "unknown"}

## ルール
- 金額は数値(int)で返す。「3千円」→3000、「1万円」→10000、「1.5k」→1500
- 曖昧でも最善の推測をする
- 「タクシー2500円だった」「ランチ1200円払った」→ record
- 「昨日の飲み 8000円 4人」→ warikan
- 「田中と山田と鈴木で割り勘」→ members (人数が分かれば set_people も)
- 「いくら？」「今いくら？」「状況は？」「合計は？」→ status
- 「清算して」「計算して」「まとめて」→ settle
- 「OK」「了解」「ありがとう」→ unknown
- JSONのみを返し、それ以外のテキストは含めないこと
"""


@dataclass
class AIParseResult:
    action: str
    amount: Optional[int] = None
    people: Optional[int] = None
    label: Optional[str] = None
    payer: Optional[str] = None
    names: Optional[list[str]] = None
    raw_response: Optional[str] = None


async def parse_with_ai(text: str) -> Optional[AIParseResult]:
    """Groq APIでメッセージを解析する。API未設定やエラー時はNoneを返す。"""
    api_key = _get_api_key()
    if not api_key:
        logger.debug("GROQ_API_KEY not set, skipping AI parsing")
        return None

    try:
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GROQ_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        raw = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        # JSONブロックを抽出（```json ... ``` で囲まれている場合に対応）
        json_str = raw
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = raw[start:end]

        parsed = json.loads(json_str)
        logger.info("AI parsed: %s -> %s", text[:50], parsed)

        return AIParseResult(
            action=parsed.get("action", "unknown"),
            amount=parsed.get("amount"),
            people=parsed.get("people"),
            label=parsed.get("label"),
            payer=parsed.get("payer"),
            names=parsed.get("names"),
            raw_response=raw,
        )

    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("AI parsing failed: %s", e)
        return None
