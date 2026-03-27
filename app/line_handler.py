"""LINEメッセージハンドラー"""
import re
from dataclasses import dataclass, field
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
    get_wizard,
    set_wizard,
    clear_wizard,
    WizardState,
)
from app.ai_parser import parse_with_ai, chat_with_ai, AIParseResult


@dataclass
class QuickReplyItem:
    """LINE Quick Reply ボタン1つ分"""
    label: str
    text: str


@dataclass
class BotResponse:
    """ボットの応答（テキスト + オプションのクイックリプライ）"""
    text: str
    quick_replies: list[QuickReplyItem] = field(default_factory=list)

    def to_line_message(self) -> dict:
        """LINE Messaging API のメッセージオブジェクトに変換する"""
        msg: dict = {"type": "text", "text": self.text}
        if self.quick_replies:
            msg["quickReply"] = {
                "items": [
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": qr.label,
                            "text": qr.text,
                        },
                    }
                    for qr in self.quick_replies
                ]
            }
        return msg


# ── クイックリプライのプリセット ──────────────────────

QR_MAIN = [
    QuickReplyItem("💰 支払い記録", "記録"),
    QuickReplyItem("� 割り勘計算", "割り勘"),
    QuickReplyItem("�👥 メンバー登録", "メンバー登録"),
    QuickReplyItem("📋 状況確認", "今いくら？"),
    QuickReplyItem("💸 精算", "精算して"),
    QuickReplyItem("❓ ヘルプ", "ヘルプ"),
]

QR_AFTER_RECORD = [
    QuickReplyItem("➕ もう1件記録", "記録"),
    QuickReplyItem("📋 状況確認", "今いくら？"),
    QuickReplyItem("💸 精算", "精算して"),
]

QR_AFTER_MEMBERS = [
    QuickReplyItem("💰 支払い記録", "記録"),
    QuickReplyItem("📋 状況確認", "今いくら？"),
]

QR_STATUS = [
    QuickReplyItem("💰 支払い記録", "記録"),
    QuickReplyItem("💸 精算", "精算して"),
    QuickReplyItem("🗑️ リセット", "リセット"),
]

QR_AFTER_SETTLE = [
    QuickReplyItem("🗑️ リセット", "リセット"),
    QuickReplyItem("📋 状況確認", "今いくら？"),
]

QR_AFTER_RESET = [
    QuickReplyItem("👥 メンバー登録", "メンバー登録"),
    QuickReplyItem("💰 支払い記録", "記録"),
    QuickReplyItem("❓ ヘルプ", "ヘルプ"),
]

HELP_TEXT = """\
💰 割り勘Bot の使い方

自然な言葉でOK！例えば:
  「昨日の飲み会8000円、4人」
  「田中がランチ1500円払った」
  「タクシー代2500円ね」
  「今いくら？」
  「清算して」

【一部のメンバーで割り勘】
  「タクシー3000円、田中と山田で割り勘」

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

_AMOUNT_PATTERN = re.compile(
    r"([0-9,，]+)\s*(?:円|えん)?$",
)

# ── よく使う項目のプリセット ──────────────────────

_COMMON_LABELS = ["ランチ", "ディナー", "飲み会", "タクシー", "コンビニ", "カフェ"]


# ── ウィザード処理 ────────────────────────────

def _start_record_wizard(group_id: str) -> BotResponse:
    """支払い記録ウィザードを開始する"""
    set_wizard(group_id, WizardState(wizard_type="record", step="amount"))
    return BotResponse(
        "💰 支払い記録\n\n"
        "① 金額を入力してください（数字のみでOK）",
        [QuickReplyItem("❌ キャンセル", "キャンセル")],
    )


def _start_warikan_wizard(group_id: str) -> BotResponse:
    """即時割り勘ウィザードを開始する"""
    set_wizard(group_id, WizardState(wizard_type="warikan", step="amount"))
    return BotResponse(
        "💴 割り勘計算\n\n"
        "① 合計金額を入力してください",
        [QuickReplyItem("❌ キャンセル", "キャンセル")],
    )


def _parse_amount_input(text: str) -> Optional[int]:
    """ユーザー入力から金額を抽出する"""
    t = text.strip().replace(",", "").replace("，", "").replace("円", "").replace("えん", "")
    if t.isdigit() and int(t) > 0:
        return int(t)
    m = _AMOUNT_PATTERN.match(text.strip())
    if m:
        val = int(m.group(1).replace(",", "").replace("，", ""))
        if val > 0:
            return val
    return None


def _parse_people_input(text: str) -> Optional[int]:
    """ユーザー入力から人数を抽出する"""
    t = text.strip().replace("人", "").replace("にん", "").replace("名", "")
    if t.isdigit() and int(t) > 0:
        return int(t)
    return None


def _handle_wizard(text: str, group_id: str) -> Optional[BotResponse]:
    """ウィザード進行中ならステップを処理する。ウィザードがなければNone。"""
    wizard = get_wizard(group_id)
    if wizard is None:
        return None

    t = text.strip()

    # キャンセル
    if t in ("キャンセル", "やめる", "cancel", "戻る"):
        clear_wizard(group_id)
        return BotResponse("❌ 入力をキャンセルしました。", QR_MAIN)

    if wizard.wizard_type == "record":
        return _handle_record_wizard(t, group_id, wizard)
    elif wizard.wizard_type == "warikan":
        return _handle_warikan_wizard(t, group_id, wizard)

    clear_wizard(group_id)
    return None


def _handle_record_wizard(
    text: str, group_id: str, wizard: WizardState,
) -> BotResponse:
    """支払い記録ウィザードのステップ処理"""
    session = get_session(group_id)
    cancel_qr = QuickReplyItem("❌ キャンセル", "キャンセル")

    # ── Step 1: 金額 ──
    if wizard.step == "amount":
        amount = _parse_amount_input(text)
        if amount is None:
            return BotResponse(
                "⚠️ 金額を数字で入力してください。\n例: 1500",
                [cancel_qr],
            )
        wizard.data["amount"] = amount
        wizard.step = "label"
        set_wizard(group_id, wizard)
        label_qrs = [QuickReplyItem(f"📝 {lb}", lb) for lb in _COMMON_LABELS]
        label_qrs.append(cancel_qr)
        return BotResponse(
            f"💰 金額: {amount:,}円\n\n"
            "② 何の支払い？（項目名を入力 or 選択）",
            label_qrs,
        )

    # ── Step 2: 項目名 ──
    if wizard.step == "label":
        wizard.data["label"] = text
        wizard.step = "payer"
        set_wizard(group_id, wizard)
        payer_qrs: list[QuickReplyItem] = []
        if session.members:
            for name in session.members[:10]:
                payer_qrs.append(QuickReplyItem(f"👤 {name}", name))
        payer_qrs.append(QuickReplyItem("⏭️ スキップ", "スキップ"))
        payer_qrs.append(cancel_qr)
        return BotResponse(
            f"💰 金額: {wizard.data['amount']:,}円\n"
            f"📝 項目: {text}\n\n"
            "③ 誰が払った？（名前を入力 or 選択）",
            payer_qrs,
        )

    # ── Step 3: 支払者 ──
    if wizard.step == "payer":
        payer = None if text in ("スキップ", "なし", "skip") else text
        wizard.data["payer"] = payer

        # メンバーが3人以上なら対象者を聞く
        if session.members and len(session.members) >= 3:
            wizard.step = "participants"
            set_wizard(group_id, wizard)
            part_qrs: list[QuickReplyItem] = [
                QuickReplyItem("👥 全員", "全員"),
            ]
            for name in session.members[:10]:
                part_qrs.append(QuickReplyItem(f"👤 {name}", name))
            part_qrs.append(cancel_qr)
            payer_display = payer or "未指定"
            return BotResponse(
                f"💰 金額: {wizard.data['amount']:,}円\n"
                f"📝 項目: {wizard.data['label']}\n"
                f"💳 支払者: {payer_display}\n\n"
                "④ 誰の分？（「全員」or 名前をカンマ区切りで入力）",
                part_qrs,
            )

        # メンバー少ない or 未設定 → 完了
        return _finish_record_wizard(group_id, wizard)

    # ── Step 4: 対象者 ──
    if wizard.step == "participants":
        participants = None
        if text not in ("全員", "みんな", "all"):
            names = re.split(r"[,、，\s]+", text)
            names = [n.strip() for n in names if n.strip()]
            if names:
                participants = names
        wizard.data["participants"] = participants
        return _finish_record_wizard(group_id, wizard)

    clear_wizard(group_id)
    return BotResponse("⚠️ 予期しないエラーです。最初からやり直してください。", QR_MAIN)


def _finish_record_wizard(group_id: str, wizard: WizardState) -> BotResponse:
    """ウィザードのデータを使って支払い記録を確定する"""
    clear_wizard(group_id)
    amount = wizard.data["amount"]
    label = wizard.data["label"]
    payer = wizard.data.get("payer")
    participants = wizard.data.get("participants")
    result_text = _do_record(group_id, amount, label, payer, participants)
    return BotResponse(result_text, QR_AFTER_RECORD)


def _handle_warikan_wizard(
    text: str, group_id: str, wizard: WizardState,
) -> BotResponse:
    """即時割り勘ウィザードのステップ処理"""
    cancel_qr = QuickReplyItem("❌ キャンセル", "キャンセル")

    # ── Step 1: 金額 ──
    if wizard.step == "amount":
        amount = _parse_amount_input(text)
        if amount is None:
            return BotResponse(
                "⚠️ 合計金額を数字で入力してください。\n例: 8000",
                [cancel_qr],
            )
        wizard.data["amount"] = amount
        wizard.step = "people"
        set_wizard(group_id, wizard)
        people_qrs = [
            QuickReplyItem(f"{n}人", str(n)) for n in range(2, 7)
        ]
        people_qrs.append(cancel_qr)
        return BotResponse(
            f"💰 合計: {amount:,}円\n\n"
            "② 何人で割る？",
            people_qrs,
        )

    # ── Step 2: 人数 ──
    if wizard.step == "people":
        people = _parse_people_input(text)
        if people is None:
            return BotResponse(
                "⚠️ 人数を数字で入力してください。\n例: 4",
                [cancel_qr],
            )
        clear_wizard(group_id)
        return BotResponse(_do_warikan(wizard.data["amount"], people))

    clear_wizard(group_id)
    return BotResponse("⚠️ 予期しないエラーです。最初からやり直してください。", QR_MAIN)


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
            part_str = ""
            if p.participants:
                part_str = f" [{','.join(p.participants)}]"
            lines.append(f"  {i}. {p.label}: {p.amount:,}円{payer_str}{part_str}")
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


def _handle_regex(text: str, group_id: str) -> Optional[BotResponse]:
    """正規表現ベースのパース。マッチしなければNoneを返す。"""
    t = text.strip()

    # ウィザード開始トリガー
    if t in ("記録", "支払い記録", "記録する"):
        return _start_record_wizard(group_id)
    if t in ("割り勘", "割り勘計算", "割り勘する"):
        return _start_warikan_wizard(group_id)

    # ヘルプ
    if t in ("ヘルプ", "へるぷ", "help", "?", "？"):
        return BotResponse(HELP_TEXT, QR_MAIN)

    # リセット
    if t in ("リセット", "りせっと", "reset", "クリア"):
        reset_session(group_id)
        clear_wizard(group_id)
        return BotResponse("🗑️ 記録をリセットしました！", QR_AFTER_RESET)

    # メンバー設定
    parsed_members = parse_member_message(t)
    if parsed_members:
        session = get_session(group_id)
        session.set_members(parsed_members)
        set_people(group_id, len(parsed_members))
        names_str = "、".join(parsed_members)
        return BotResponse(
            f"👥 メンバーを登録しました ({len(parsed_members)}人):\n"
            f"  {names_str}",
            QR_AFTER_MEMBERS,
        )

    # 人数セット
    m = _PEOPLE_SET_PATTERN.match(t)
    if m:
        people = int(m.group(1).replace(",", "").replace("，", ""))
        if people <= 0:
            return BotResponse("人数は1以上にしてください。")
        set_people(group_id, people)
        return BotResponse(f"👤 人数を {people}人 にセットしました。", QR_AFTER_MEMBERS)

    # 精算・清算
    if _SETTLE_PATTERN.search(t) or t in ("合計", "ごうけい"):
        return BotResponse(_do_settle(group_id), QR_AFTER_SETTLE)

    # 状況確認
    if _STATUS_PATTERN.search(t):
        return BotResponse(_format_status(group_id), QR_STATUS)

    # 記録 (「記録 1500円 ランチ」形式)
    parsed_record = parse_record_message(t)
    if parsed_record:
        amount, label, payer = parsed_record
        if amount <= 0:
            return BotResponse("金額は1以上にしてください。")
        return BotResponse(_do_record(group_id, amount, label, payer), QR_AFTER_RECORD)

    # 即時割り勘
    parsed = parse_warikan_message(t)
    if parsed:
        total, people = parsed
        if total <= 0:
            return BotResponse("金額は1以上にしてください。")
        if people <= 0:
            return BotResponse("人数は1以上にしてください。")
        return BotResponse(_do_warikan(total, people))

    # 自然言語の支払い記録 (「ランチ1500円」「田中がタクシー2500円払った」)
    parsed_natural = parse_natural_record_message(t)
    if parsed_natural:
        amount, label, payer = parsed_natural
        if amount <= 0:
            return BotResponse("金額は1以上にしてください。")
        return BotResponse(_do_record(group_id, amount, label, payer), QR_AFTER_RECORD)

    return None


def _do_warikan(total: int, people: int) -> str:
    """即時割り勘計算（テキストのみ返す内部関数）"""
    try:
        result = calculate_warikan(total, people)
    except ValueError as e:
        return str(e)
    return f"💴 割り勘計算\n{result.description}"


def _do_record(
    group_id: str,
    amount: int,
    label: str,
    payer: Optional[str] = None,
    participants: Optional[list[str]] = None,
) -> str:
    """支払い記録"""
    session = get_session(group_id)
    payer_warning = ""
    if payer and session.members and payer not in session.members:
        payer_warning = f"\n⚠️ {payer}はメンバー未登録です。"
    session.add_payment(amount, label, payer, participants)
    payer_str = f" ({payer})" if payer else ""
    part_str = ""
    if participants:
        part_str = f"\n👥 対象: {'、'.join(participants)}"
    return _append_status(
        f"✅ 記録: {label} {amount:,}円{payer_str}{part_str}{payer_warning}",
        group_id,
    )


def _do_settle(group_id: str) -> str:
    """精算"""
    people = get_people(group_id)
    if people is None:
        return "先に人数かメンバーを教えてください。\n例: 「4人」「メンバーは田中と山田と鈴木」"
    session = get_session(group_id)
    return calculate_settlement(session, people)


def _process_ai_result(result: AIParseResult, group_id: str) -> Optional[BotResponse]:
    """AIParseResultを処理してレスポンスを返す。unknownの場合はNoneを返す。"""
    action = result.action

    if action == "unknown":
        return None

    if action == "help":
        return BotResponse(HELP_TEXT, QR_MAIN)

    if action == "reset":
        reset_session(group_id)
        return BotResponse("🗑️ 記録をリセットしました！", QR_AFTER_RESET)

    if action == "status":
        return BotResponse(_format_status(group_id), QR_STATUS)

    if action == "settle":
        return BotResponse(_do_settle(group_id), QR_AFTER_SETTLE)

    if action == "warikan" and result.amount and result.people:
        return BotResponse(_do_warikan(result.amount, result.people))

    if action == "record" and result.amount:
        label = result.label or "支払い"
        return BotResponse(
            _do_record(
                group_id, result.amount, label, result.payer, result.participants,
            ),
            QR_AFTER_RECORD,
        )

    if action == "members" and result.names:
        session = get_session(group_id)
        session.set_members(result.names)
        set_people(group_id, len(result.names))
        names_str = "、".join(result.names)
        return BotResponse(
            f"👥 メンバーを登録しました ({len(result.names)}人):\n"
            f"  {names_str}",
            QR_AFTER_MEMBERS,
        )

    if action == "set_people" and result.people:
        if result.people <= 0:
            return BotResponse("人数は1以上にしてください。")
        set_people(group_id, result.people)
        return BotResponse(
            f"👤 人数を {result.people}人 にセットしました。",
            QR_AFTER_MEMBERS,
        )

    if action == "ask" and result.message:
        return BotResponse(f"💡 {result.message}", QR_MAIN)

    if action == "advice" and result.message:
        return BotResponse(f"💬 {result.message}", QR_MAIN)

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


async def handle_text(text: str, group_id: str) -> BotResponse:
    """テキストメッセージを解釈してBotResponseを返す"""

    # 0. ウィザード進行中ならそちらを優先
    wizard_result = _handle_wizard(text, group_id)
    if wizard_result is not None:
        return wizard_result

    # 1. まず正規表現ベースでパース（高速・確実）
    regex_result = _handle_regex(text, group_id)
    if regex_result is not None:
        return regex_result

    # 2. AIパースにフォールバック（セッション情報を渡す）
    session_info = _get_session_info(group_id)
    parse_result = await parse_with_ai(text, session_info=session_info)

    # 2a. AIエラー → ヘルプ誘導
    if parse_result is None:
        return BotResponse(HELP_TEXT, QR_MAIN)

    # 2b. 割り勘アクションと判断 → 処理
    warikan_result = _process_ai_result(parse_result, group_id)
    if warikan_result is not None:
        return warikan_result

    # 2c. 割り勘と関係ない（unknown）→ AI会話応答
    chat_response = await chat_with_ai(text, session_info=session_info)
    if chat_response:
        return BotResponse(chat_response, QR_MAIN)

    # 2d. チャットもエラー → ヘルプ誘導
    return BotResponse(HELP_TEXT, QR_MAIN)
