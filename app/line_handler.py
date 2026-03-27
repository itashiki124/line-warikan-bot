"""LINEメッセージハンドラー"""
import re
from typing import Optional
from app.warikan import (
    calculate_warikan,
    calculate_settlement,
    parse_warikan_message,
    parse_record_message,
    parse_member_message,
    parse_natural_record_message,
    GroupSession,
)
from app.storage import (
    get_session,
    reset_session,
    get_people,
    set_people,
)
from app.ai_parser import parse_with_ai, chat_with_ai, AIParseResult

HELP_TEXT = """\
💰 割り勘Bot の使い方

自然な言葉でOK！例えば:
  「昨日の飲み会8000円、4人」
  「田中がランチ1500円払った」
  「タクシー代2500円ね」
  「今いくら？」
  「清算して」

【メンバー登録】
  「メンバーは田中と山田と鈴木」

【その他】
  リセット / ヘルプ
"""

_PEOPLE_SET_PATTERN = re.compile(
    r"^(?:人数|にんずう|members?)\s*([0-9,，]+)\s*(?:人|にん|名)?$",
    re.IGNORECASE,
)

_STATUS_PATTERN = re.compile(
    r"^(?:今|いま)?(?:いくら|幾ら)\s*[？?]?$|"
    r"^(?:合計|ごうけい|状況|現在の?状況|確認)\s*[はをが]?\s*[？?]?$",
    re.IGNORECASE,
)

_SETTLE_PATTERN = re.compile(
    r"(?:精算|清算|せいさん|settle)(?:して|しよう|する|お願い)?[！!]?",
    re.IGNORECASE,
)


def _format_status(group_id: str) -> str:
    """現在の集計状況を生成する"""
    session = get_session(group_id)
    people = get_people(group_id)

    if not session.payments and not session.members:
        return "📋 まだ記録がありません。"

    lines = ["📋 現在の集計状況"]
    lines.append("─" * 18)

    if session.members:
        lines.append(f"👥 メンバー: {', '.join(session.members)}")

    if people:
        lines.append(f"👤 人数: {people}人")

    if session.payments:
        lines.append(f"\n【支払い一覧】({len(session.payments)}件)")
        for i, p in enumerate(session.payments, 1):
            payer_str = f" ({p.payer})" if p.payer else ""
            lines.append(f"  {i}. {p.label}: {p.amount:,}円{payer_str}")
        lines.append(f"\n💰 合計: {session.total():,}円")
        if people:
            per_person = session.total() // people
            lines.append(f"📐 1人あたり約 {per_person:,}円")
    else:
        lines.append("\n支払い記録はまだありません。")

    return "\n".join(lines)


def _append_status(response: str, group_id: str) -> str:
    """レスポンスの後に現在の集計状況を追加する"""
    session = get_session(group_id)
    if not session.payments:
        return response

    people = get_people(group_id)
    count = len(session.payments)
    total = session.total()
    status = f"\n\n📋 現在: {count}件 / 合計 {total:,}円"
    if people:
        status += f" / {people}人"
    return response + status


def _handle_regex(text: str, group_id: str) -> Optional[str]:
    """正規表現ベースのパース。マッチしなければNoneを返す。"""
    t = text.strip()

    # ヘルプ
    if t in ("ヘルプ", "へるぷ", "help", "?", "？"):
        return HELP_TEXT

    # リセット
    if t in ("リセット", "りせっと", "reset", "クリア"):
        reset_session(group_id)
        return "🗑️ 記録をリセットしました！"

    # メンバー設定
    parsed_members = parse_member_message(t)
    if parsed_members:
        session = get_session(group_id)
        session.set_members(parsed_members)
        set_people(group_id, len(parsed_members))
        names_str = "、".join(parsed_members)
        return (
            f"👥 メンバーを登録しました ({len(parsed_members)}人):\n"
            f"  {names_str}"
        )

    # 人数セット
    m = _PEOPLE_SET_PATTERN.match(t)
    if m:
        people = int(m.group(1).replace(",", "").replace("，", ""))
        if people <= 0:
            return "人数は1以上にしてください。"
        set_people(group_id, people)
        return f"👤 人数を {people}人 にセットしました。"

    # 精算・清算
    if _SETTLE_PATTERN.search(t) or t in ("合計", "ごうけい"):
        return _do_settle(group_id)

    # 状況確認
    if _STATUS_PATTERN.search(t):
        return _format_status(group_id)

    # 記録 (「記録 1500円 ランチ」形式)
    parsed_record = parse_record_message(t)
    if parsed_record:
        amount, label, payer = parsed_record
        if amount <= 0:
            return "金額は1以上にしてください。"
        return _do_record(group_id, amount, label, payer)

    # 即時割り勘
    parsed = parse_warikan_message(t)
    if parsed:
        total, people = parsed
        if total <= 0:
            return "金額は1以上にしてください。"
        if people <= 0:
            return "人数は1以上にしてください。"
        return _do_warikan(total, people)

    # 自然言語の支払い記録 (「ランチ1500円」「田中がタクシー2500円払った」)
    parsed_natural = parse_natural_record_message(t)
    if parsed_natural:
        amount, label, payer = parsed_natural
        if amount <= 0:
            return "金額は1以上にしてください。"
        return _do_record(group_id, amount, label, payer)

    return None


def _do_warikan(total: int, people: int) -> str:
    """即時割り勘計算"""
    try:
        result = calculate_warikan(total, people)
    except ValueError as e:
        return str(e)
    return f"💴 割り勘計算\n{result.description}"


def _do_record(group_id: str, amount: int, label: str, payer: Optional[str] = None) -> str:
    """支払い記録"""
    session = get_session(group_id)
    payer_warning = ""
    if payer and session.members and payer not in session.members:
        payer_warning = f"\n⚠️ {payer}はメンバー未登録です。"
    session.add_payment(amount, label, payer)
    payer_str = f" ({payer})" if payer else ""
    return _append_status(
        f"✅ 記録: {label} {amount:,}円{payer_str}{payer_warning}",
        group_id,
    )


def _do_settle(group_id: str) -> str:
    """精算"""
    people = get_people(group_id)
    if people is None:
        return "先に人数かメンバーを教えてください。\n例: 「4人」「メンバーは田中と山田と鈴木」"
    session = get_session(group_id)
    return calculate_settlement(session, people)


def _process_ai_result(result: AIParseResult, group_id: str) -> Optional[str]:
    """AIParseResultを処理してレスポンスを返す。unknownの場合はNoneを返す。"""
    action = result.action

    if action == "unknown":
        return None

    if action == "help":
        return HELP_TEXT

    if action == "reset":
        reset_session(group_id)
        return "🗑️ 記録をリセットしました！"

    if action == "status":
        return _format_status(group_id)

    if action == "settle":
        return _do_settle(group_id)

    if action == "warikan" and result.amount and result.people:
        return _do_warikan(result.amount, result.people)

    if action == "record" and result.amount:
        label = result.label or "支払い"
        return _do_record(group_id, result.amount, label, result.payer)

    if action == "members" and result.names:
        session = get_session(group_id)
        session.set_members(result.names)
        set_people(group_id, len(result.names))
        names_str = "、".join(result.names)
        return (
            f"👥 メンバーを登録しました ({len(result.names)}人):\n"
            f"  {names_str}"
        )

    if action == "set_people" and result.people:
        if result.people <= 0:
            return "人数は1以上にしてください。"
        set_people(group_id, result.people)
        return f"👤 人数を {result.people}人 にセットしました。"

    if action == "ask" and result.message:
        return f"💡 {result.message}"

    if action == "advice" and result.message:
        return f"💬 {result.message}"

    return None


def _get_session_info(group_id: str) -> dict:
    """セッションの現在情報をdictで返す（AIにコンテキストとして渡す用）"""
    session = get_session(group_id)
    people = get_people(group_id)
    return {
        "members": session.members,
        "people": people,
        "payment_count": len(session.payments),
        "total": session.total() if session.payments else 0,
    }


async def handle_text(text: str, group_id: str) -> str:
    """テキストメッセージを解釈してレスポンス文字列を返す"""

    # 1. まず正規表現ベースでパース（高速・確実）
    regex_result = _handle_regex(text, group_id)
    if regex_result is not None:
        return regex_result

    # 2. AIパースにフォールバック（セッション情報を渡す）
    session_info = _get_session_info(group_id)
    parse_result = await parse_with_ai(text, session_info=session_info)

    # 2a. AIエラー → ヘルプ誘導
    if parse_result is None:
        return HELP_TEXT

    # 2b. 割り勘アクションと判断 → 処理
    warikan_result = _process_ai_result(parse_result, group_id)
    if warikan_result is not None:
        return warikan_result

    # 2c. 割り勘と関係ない（unknown）→ AI会話応答
    chat_response = await chat_with_ai(text, session_info=session_info)
    if chat_response:
        return chat_response

    # 2d. チャットもエラー → ヘルプ誘導
    return HELP_TEXT
