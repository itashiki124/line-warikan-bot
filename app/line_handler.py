"""LINEメッセージハンドラー"""
import re
from app.warikan import (
    calculate_warikan,
    calculate_settlement,
    parse_warikan_message,
    parse_record_message,
    parse_member_message,
)
from app.storage import (
    get_session,
    reset_session,
    get_people,
    set_people,
)

HELP_TEXT = """\
💰 割り勘Bot の使い方

【即時計算】
  3000円 3人
  飲み会5000円を4人で
  → 金額と人数があればOK！

【支払いを記録して精算】
  人数 4人               … 人数をセット
  メンバー 田中 山田 鈴木 佐藤 … メンバー登録
  記録 田中 3000円 ランチ  … 誰が払ったか記録
  記録 1200円 コーヒー    … 支払者なしでもOK
  精算                   … 合計＋誰→誰に払うか計算

【その他】
  リセット  … 記録をクリア
  ヘルプ    … この説明を表示
"""

_PEOPLE_SET_PATTERN = re.compile(
    r"^(?:人数|にんずう|members?)\s*([0-9,，]+)\s*(?:人|にん|名)?$",
    re.IGNORECASE,
)


def handle_text(text: str, group_id: str) -> str:
    """テキストメッセージを解釈してレスポンス文字列を返す"""
    t = text.strip()

    # ヘルプ
    if t in ("ヘルプ", "へるぷ", "help", "?", "？"):
        return HELP_TEXT

    # リセット
    if t in ("リセット", "りせっと", "reset", "クリア"):
        reset_session(group_id)
        return "記録をリセットしました！"

    # メンバー設定: 「メンバー 田中 山田 鈴木」
    parsed_members = parse_member_message(t)
    if parsed_members:
        session = get_session(group_id)
        session.set_members(parsed_members)
        set_people(group_id, len(parsed_members))
        names_str = "、".join(parsed_members)
        return (
            f"メンバーを登録しました ({len(parsed_members)}人):\n"
            f"  {names_str}\n\n"
            "「記録 名前 金額 説明」で支払いを追加できます。"
        )

    # 人数セット: 「人数 4人」
    m = _PEOPLE_SET_PATTERN.match(t)
    if m:
        people = int(m.group(1).replace(",", "").replace("，", ""))
        if people <= 0:
            return "人数は1以上にしてください。"
        set_people(group_id, people)
        return f"人数を {people}人 にセットしました。\n「記録 金額 説明」で支払いを追加できます。"

    # 精算
    if t in ("精算", "せいさん", "settle", "合計", "ごうけい"):
        people = get_people(group_id)
        if people is None:
            return "先に「人数 〇人」または「メンバー 名前...」で人数をセットしてください。"
        session = get_session(group_id)
        return calculate_settlement(session, people)

    # 記録: 「記録 [支払者] 1500円 ランチ」
    parsed_record = parse_record_message(t)
    if parsed_record:
        amount, label, payer = parsed_record
        if amount <= 0:
            return "金額は1以上にしてください。"
        session = get_session(group_id)
        # 支払者がメンバーに含まれていない場合の警告
        payer_warning = ""
        if payer and session.members and payer not in session.members:
            payer_warning = f"\n⚠️ {payer}はメンバーに登録されていません。「メンバー」で確認してください。"
        session.add_payment(amount, label, payer)
        total = session.total()
        count = len(session.payments)
        payer_str = f" ({payer})" if payer else ""
        return (
            f"✅ 記録しました: {label} {amount:,}円{payer_str}\n"
            f"累計 {count}件 / 合計 {total:,}円{payer_warning}\n\n"
            "「精算」で割り勘計算できます。"
        )

    # 即時割り勘: 「3000円 3人」「飲み会5000円4人で割って」etc.
    parsed = parse_warikan_message(t)
    if parsed:
        total, people = parsed
        if total <= 0:
            return "金額は1以上にしてください。"
        if people <= 0:
            return "人数は1以上にしてください。"
        try:
            result = calculate_warikan(total, people)
        except ValueError as e:
            return str(e)

        lines = [f"💴 割り勘計算"]
        lines.append(result.description)
        return "\n".join(lines)

    # 未認識
    return (
        "メッセージを認識できませんでした。\n"
        "例: 「3000円 3人」「飲み会5000円を4人で」\n"
        "「ヘルプ」で使い方を確認できます。"
    )
