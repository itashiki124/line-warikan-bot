"""割り勘計算ロジック"""
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class WarikanResult:
    total: int
    people: int
    base_amount: int
    remainder: int
    # remainder人が(base_amount+1)円を払う
    description: str


@dataclass
class Payment:
    amount: int
    label: str


@dataclass
class GroupSession:
    payments: list[Payment] = field(default_factory=list)

    def add_payment(self, amount: int, label: str) -> None:
        self.payments.append(Payment(amount=amount, label=label))

    def total(self) -> int:
        return sum(p.amount for p in self.payments)

    def reset(self) -> None:
        self.payments.clear()


def calculate_warikan(total: int, people: int) -> WarikanResult:
    """割り勘計算。端数は一部の人が多く払う形で処理する。"""
    if people <= 0:
        raise ValueError("人数は1以上にしてください")
    if total < 0:
        raise ValueError("金額は0以上にしてください")

    base_amount = total // people
    remainder = total % people

    lines = []
    lines.append(f"合計: {total:,}円 / {people}人")
    lines.append("")

    if remainder == 0:
        lines.append(f"全員: 1人あたり {base_amount:,}円")
    else:
        lines.append(f"{remainder}人: {base_amount + 1:,}円")
        lines.append(f"{people - remainder}人: {base_amount:,}円")
        lines.append("")
        lines.append(f"（端数 {remainder}円を{remainder}人に分配）")

    description = "\n".join(lines)
    return WarikanResult(
        total=total,
        people=people,
        base_amount=base_amount,
        remainder=remainder,
        description=description,
    )


def calculate_settlement(session: GroupSession, people: int) -> str:
    """複数支払いの精算計算"""
    if not session.payments:
        return "記録された支払いがありません。\n「記録 1500円 ランチ」のように入力してください。"

    total = session.total()
    result = calculate_warikan(total, people)

    lines = ["📊 精算結果"]
    lines.append("─" * 20)
    lines.append("【支払い一覧】")
    for i, p in enumerate(session.payments, 1):
        lines.append(f"  {i}. {p.label}: {p.amount:,}円")
    lines.append(f"\n合計: {total:,}円")
    lines.append(f"人数: {people}人")
    lines.append("")
    lines.append("【1人あたりの負担】")
    if result.remainder == 0:
        lines.append(f"  全員: {result.base_amount:,}円")
    else:
        lines.append(f"  {result.remainder}人: {result.base_amount + 1:,}円")
        lines.append(f"  {people - result.remainder}人: {result.base_amount:,}円")

    return "\n".join(lines)


# パースユーティリティ

_AMOUNT_PATTERN = re.compile(
    r"(?:¥|￥)?([0-9,，]+)\s*(?:円|えん)?", re.IGNORECASE
)
_PEOPLE_PATTERN = re.compile(
    r"([0-9,，]+)\s*(?:人|にん|名|めい)", re.IGNORECASE
)
_RECORD_PATTERN = re.compile(
    r"(?:記録|きろく|add)\s+"
    r"(?:¥|￥)?([0-9,，]+)\s*(?:円|えん)?\s*(.+)?",
    re.IGNORECASE,
)


def _clean_number(s: str) -> int:
    return int(s.replace(",", "").replace("，", ""))


def parse_warikan_message(text: str) -> Optional[tuple[int, int]]:
    """「3000円 3人」形式をパース。(total, people) を返す。"""
    text = text.strip()
    amount_match = _AMOUNT_PATTERN.search(text)
    people_match = _PEOPLE_PATTERN.search(text)
    if amount_match and people_match:
        return _clean_number(amount_match.group(1)), _clean_number(people_match.group(1))
    return None


def parse_record_message(text: str) -> Optional[tuple[int, str]]:
    """「記録 1500円 ランチ」形式をパース。(amount, label) を返す。"""
    m = _RECORD_PATTERN.match(text.strip())
    if m:
        amount = _clean_number(m.group(1))
        label = (m.group(2) or "支払い").strip()
        return amount, label
    return None
