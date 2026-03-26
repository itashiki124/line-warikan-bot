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
    payer: Optional[str] = None


@dataclass
class Transfer:
    """精算時の送金指示"""
    from_person: str
    to_person: str
    amount: int


@dataclass
class GroupSession:
    payments: list[Payment] = field(default_factory=list)
    members: list[str] = field(default_factory=list)

    def add_payment(self, amount: int, label: str, payer: Optional[str] = None) -> None:
        self.payments.append(Payment(amount=amount, label=label, payer=payer))

    def total(self) -> int:
        return sum(p.amount for p in self.payments)

    def reset(self) -> None:
        self.payments.clear()
        self.members.clear()

    def set_members(self, names: list[str]) -> None:
        self.members = list(names)

    def has_payer_info(self) -> bool:
        """支払者情報が1件でもあるか"""
        return any(p.payer is not None for p in self.payments)


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


def calculate_transfers(session: GroupSession, people: int) -> list[Transfer]:
    """各メンバーの立替額と負担額から、最適な送金リストを計算する。

    メンバー名が設定されていて支払者情報がある場合のみ有効。
    """
    members = session.members
    if not members or not session.has_payer_info():
        return []

    total = session.total()
    fair_share = total // people
    remainder = total % people

    # 各メンバーの「公平な負担額」 (端数は先頭メンバーから割り当て)
    shares: dict[str, int] = {}
    for i, name in enumerate(members):
        shares[name] = fair_share + (1 if i < remainder else 0)

    # 各メンバーの実際の支払額
    paid: dict[str, int] = {name: 0 for name in members}
    for p in session.payments:
        if p.payer and p.payer in paid:
            paid[p.payer] += p.amount

    # balance = 支払済み - 負担額 (正なら受取側、負なら支払側)
    balance: dict[str, int] = {
        name: paid[name] - shares[name] for name in members
    }

    # 貪欲法で送金リストを作成
    creditors = sorted(
        [(name, bal) for name, bal in balance.items() if bal > 0],
        key=lambda x: -x[1],
    )
    debtors = sorted(
        [(name, -bal) for name, bal in balance.items() if bal < 0],
        key=lambda x: -x[1],
    )

    transfers: list[Transfer] = []
    ci, di = 0, 0
    c_remain = creditors[0][1] if creditors else 0
    d_remain = debtors[0][1] if debtors else 0

    while ci < len(creditors) and di < len(debtors):
        amount = min(c_remain, d_remain)
        if amount > 0:
            transfers.append(Transfer(
                from_person=debtors[di][0],
                to_person=creditors[ci][0],
                amount=amount,
            ))
        c_remain -= amount
        d_remain -= amount
        if c_remain == 0:
            ci += 1
            if ci < len(creditors):
                c_remain = creditors[ci][1]
        if d_remain == 0:
            di += 1
            if di < len(debtors):
                d_remain = debtors[di][1]

    return transfers


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
        payer_str = f"({p.payer})" if p.payer else ""
        lines.append(f"  {i}. {p.label}: {p.amount:,}円 {payer_str}".rstrip())
    lines.append(f"\n合計: {total:,}円")
    lines.append(f"人数: {people}人")
    lines.append("")
    lines.append("【1人あたりの負担】")
    if result.remainder == 0:
        lines.append(f"  全員: {result.base_amount:,}円")
    else:
        lines.append(f"  {result.remainder}人: {result.base_amount + 1:,}円")
        lines.append(f"  {people - result.remainder}人: {result.base_amount:,}円")

    # 誰→誰にいくら払うかの精算
    transfers = calculate_transfers(session, people)
    if transfers:
        lines.append("")
        lines.append("【送金プラン】")
        for t in transfers:
            lines.append(f"  💸 {t.from_person} → {t.to_person}: {t.amount:,}円")

    return "\n".join(lines)


# パースユーティリティ

_AMOUNT_PATTERN = re.compile(
    r"(?:¥|￥)?([0-9,，]+)\s*(?:円|えん)?", re.IGNORECASE
)
_PEOPLE_PATTERN = re.compile(
    r"([0-9,，]+)\s*(?:人|にん|名|めい)", re.IGNORECASE
)

# 「記録 田中 1500円 ランチ」 or 「記録 1500円 ランチ」
_RECORD_PATTERN = re.compile(
    r"(?:記録|きろく|add)\s+"
    r"(?:(\S+?)\s+)?"
    r"(?:¥|￥)?([0-9,，]+)\s*(?:円|えん)?\s*(.*)?",
    re.IGNORECASE,
)

# メンバー設定: 「メンバー 田中 山田 鈴木」
_MEMBER_PATTERN = re.compile(
    r"^(?:メンバー|めんばー|members?)\s+(.+)$",
    re.IGNORECASE,
)

# 割り勘を想起させるキーワード
_WARIKAN_KEYWORDS = re.compile(
    r"割り勘|わりかん|割勘|ワリカン|割って|わって|精算して|せいさんして",
    re.IGNORECASE,
)


def _clean_number(s: str) -> int:
    return int(s.replace(",", "").replace("，", ""))


def _is_number_like(s: str) -> bool:
    """数字のみ（カンマ含む）かどうか"""
    return bool(re.fullmatch(r"[0-9,，]+", s))


def parse_warikan_message(text: str) -> Optional[tuple[int, int]]:
    """金額と人数を含むメッセージをパース。(total, people) を返す。

    柔軟にパースし、以下のような入力に対応:
    - 「3000円 3人」
    - 「3人で5000円」
    - 「飲み会5000円4人で割り勘」
    - 「5000円を3人で割って」
    - 「ランチ代3000円、3人で」
    """
    text = text.strip()

    # まず人数を特定
    people_match = _PEOPLE_PATTERN.search(text)
    if not people_match:
        return None

    people = _clean_number(people_match.group(1))

    # 人数部分を除外した上で金額を探す
    text_without_people = text[:people_match.start()] + text[people_match.end():]
    amount_match = _AMOUNT_PATTERN.search(text_without_people)
    if not amount_match:
        return None

    amount = _clean_number(amount_match.group(1))
    return amount, people


def parse_record_message(text: str) -> Optional[tuple[int, str, Optional[str]]]:
    """「記録 [支払者] 金額 ラベル」形式をパース。(amount, label, payer) を返す。

    - 「記録 1500円 ランチ」 → (1500, "ランチ", None)
    - 「記録 田中 1500円 ランチ」 → (1500, "ランチ", "田中")
    """
    m = _RECORD_PATTERN.match(text.strip())
    if m:
        maybe_payer = m.group(1)
        amount = _clean_number(m.group(2))
        label = (m.group(3) or "支払い").strip()

        payer: Optional[str] = None
        if maybe_payer and not _is_number_like(maybe_payer):
            payer = maybe_payer
        elif maybe_payer:
            # 数字だった場合は金額の一部かもしれないので再パース
            # 「記録 1500円 ランチ」で payer=None になるよう
            payer = None

        return amount, label, payer
    return None


def parse_member_message(text: str) -> Optional[list[str]]:
    """「メンバー 田中 山田 鈴木」形式をパース。メンバーリストを返す。"""
    m = _MEMBER_PATTERN.match(text.strip())
    if m:
        raw = m.group(1)
        # スペース、カンマ、全角カンマ、読点で分割
        names = re.split(r"[,，、\s]+", raw.strip())
        names = [n for n in names if n]
        if names:
            return names
    return None
