"""生成AIを使った自然言語メッセージの解釈モジュール

OpenAI GPT API (gpt-4o-mini) を使用して、ざっくりしたメッセージから
割り勘に必要な情報を抽出する。
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "")

SYSTEM_PROMPT = """\
あなたは割り勘計算専門のアシスタントです。ユーザーのメッセージから金額、人数、参加者名、支払い者などの割り勘に関する情報を抽出してください。割り勘と関係ない話題の場合は、割り勘Botであることを伝えて、割り勘の使い方を案内してください。

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

9. **ask** - 情報不足で質問が必要（割り勘に関連するが情報が足りない）
   {"action": "ask", "message": "ユーザーへの質問文"}

10. **advice** - 割り勘に関する相談・質問への回答
   {"action": "advice", "message": "回答テキスト"}

11. **unknown** - 割り勘に完全に関係ない会話（挨拶、雑談など）
   {"action": "unknown"}

## 金額の解釈ルール
- 数値(int)で返す
- 「3千円」→3000、「1万円」→10000、「1万5千円」→15000、「2万3千」→23000
- 「1.5万」→15000、「2.5k」→2500、「1.5k」→1500
- 「千円」→1000、「万」→10000
- 「約5000円」→5000（「約」「だいたい」「くらい」は無視してよい）

## 分類ルール・例
- 「タクシー2500円だった」「ランチ1200円払った」「俺が出した5000円」→ record
- 「昨日の飲み 8000円 4人」「3人で割ると？12000円」→ warikan
- 「田中と山田と鈴木で割り勘」→ members
- 「3人でやる」「今日は5人」→ set_people
- 「いくら？」「今いくら？」「状況は？」「合計は？」「今の記録見せて」→ status
- 「清算して」「計算して」「まとめて」「そろそろ精算」「締めよう」→ settle
- 「田中は飲まなかったから少なめで」「均等じゃなくて傾斜つけたい」→ advice（アドバイスを返す）
- 「割り勘ってどうやるの？」「使い方教えて」→ help
- 「飲み会のお金、割り勘にしたい」→ ask（金額と人数を聞く）
- 「昨日のご飯代を記録して」→ ask（金額を聞く）
- 「5000円」→ record（金額のみでも記録として扱う。label="支払い"）
- 「OK」「了解」「ありがとう」「うん」→ unknown

## 重要なルール
- 割り勘・お金に関するメッセージなら、unknownにせず、適切なアクションかask/adviceにする
- 情報が足りない場合はaskで自然な質問文を生成する
- 曖昧でも最善の推測をする。確信が持てない場合はaskで確認する
- JSONのみを返し、それ以外のテキストは含めないこと
"""


@dataclass
class AIParseResult:
    action: str
    amount: Optional[int] = None
    people: Optional[int] = None
    label: Optional[str] = None
    payer: Optional[str] = None
    names: Optional[list] = None
    message: Optional[str] = None
    raw_response: Optional[str] = None


def _build_context_message(session_info: Optional[dict] = None) -> str:
    """セッション情報をAIに渡すためのコンテキストメッセージを構築する。"""
    if not session_info:
        return ""
    parts = []
    if session_info.get("members"):
        parts.append(f"現在のメンバー: {', '.join(session_info['members'])}")
    if session_info.get("people"):
        parts.append(f"人数: {session_info['people']}人")
    if session_info.get("payment_count"):
        parts.append(f"支払い記録: {session_info['payment_count']}件")
    if session_info.get("total"):
        parts.append(f"合計: {session_info['total']}円")
    if not parts:
        return ""
    return "[現在のセッション情報] " + " / ".join(parts)


async def parse_with_ai(
    text: str,
    session_info: Optional[dict] = None,
) -> Optional[AIParseResult]:
    """OpenAI GPT APIでメッセージを解析する。API未設定やエラー時はNoneを返す。"""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("OPENAI_API_KEY not set, skipping AI parsing")
        return None

    try:
        client = AsyncOpenAI(api_key=api_key)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        context_msg = _build_context_message(session_info)
        if context_msg:
            messages.append({"role": "system", "content": context_msg})
        messages.append({"role": "user", "content": text})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            max_tokens=512,
        )

        raw = response.choices[0].message.content.strip()

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
            message=parsed.get("message"),
            raw_response=raw,
        )

    except Exception as e:
        logger.warning("AI parsing failed: %s", e, exc_info=True)
        return None


CHAT_SYSTEM_PROMPT = """\
あなたはLINEグループの割り勘Botです。名前は「割り勘Bot」です。
フレンドリーで簡潔に会話してください。

- 割り勘や支払いに関係する話題が出たら、積極的にサポートを提案してください
- 「飲み会のお金を割り勘にしたいんだけど」→ 金額と人数を聞く
- 挨拶や雑談には短く親しみやすく返す
- 使い方を聞かれたらヘルプを案内する
- 回答は簡潔に（LINEメッセージなので長文は避ける）
"""


async def chat_with_ai(text: str, session_info: Optional[dict] = None) -> Optional[str]:
    """割り勘Botとしての会話応答。API未設定やエラー時はNoneを返す。"""
    api_key = _get_api_key()
    if not api_key:
        return None

    try:
        client = AsyncOpenAI(api_key=api_key)
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        ]
        context_msg = _build_context_message(session_info)
        if context_msg:
            messages.append({"role": "system", "content": context_msg})
        messages.append({"role": "user", "content": text})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=256,
        )
        return response.choices[0].message.content.strip() or None
    except Exception as e:
        logger.warning("AI chat failed: %s", e, exc_info=True)
        return None
