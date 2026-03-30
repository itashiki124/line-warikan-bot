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
    participants: Optional[list[str]] = None  # この支払いの対象者（None=全員）


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

    def add_payment(
        self,
        amount: int,
        label: str,
        payer: Optional[str] = None,
        participants: Optional[list[str]] = None,
    ) -> None:
        self.payments.append(Payment(
            amount=amount, label=label, payer=payer, participants=participants,
        ))

    def pop_last_payment(self) -> Optional[Payment]:
        if not self.payments:
            return None
        return self.payments.pop()

    def recent_payments(self, limit: int = 5) -> list[Payment]:
        if limit <= 0:
            return []
        return self.payments[-limit:]

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
    支払いごとに participants が指定されていれば、その支払いの負担は
    対象者のみで按分する（個人間の割り勘に対応）。
    """
    members = session.members
    if not members or not session.has_payer_info():
        return []

    # 各メンバーの負担額を支払いごとに積算
    shares: dict[str, int] = {name: 0 for name in members}
    for p in session.payments:
        targets = p.participants if p.participants else members
        # targets のうちメンバーに含まれる人だけで按分
        valid_targets = [t for t in targets if t in shares]
        if not valid_targets:
            valid_targets = list(members)
        n = len(valid_targets)
        base = p.amount // n
        rem = p.amount % n
        for i, name in enumerate(valid_targets):
            shares[name] += base + (1 if i < rem else 0)

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
    has_partial = any(p.participants for p in session.payments)
    members = session.members

    lines = ["📊 精算結果"]
    lines.append("─" * 20)
    lines.append("【支払い一覧】")
    for i, p in enumerate(session.payments, 1):
        payer_str = f"({p.payer})" if p.payer else ""
        part_str = ""
        if p.participants:
            part_str = f" [{','.join(p.participants)}]"
        lines.append(f"  {i}. {p.label}: {p.amount:,}円 {payer_str}{part_str}".rstrip())
    lines.append(f"\n合計: {total:,}円")
    lines.append(f"人数: {people}人")

    # メンバーごとの負担額を計算して表示
    if members and (has_partial or session.has_payer_info()):
        shares: dict[str, int] = {name: 0 for name in members}
        for p in session.payments:
            targets = p.participants if p.participants else members
            valid_targets = [t for t in targets if t in shares]
            if not valid_targets:
                valid_targets = list(members)
            n = len(valid_targets)
            base = p.amount // n
            rem = p.amount % n
            for j, name in enumerate(valid_targets):
                shares[name] += base + (1 if j < rem else 0)

        lines.append("")
        lines.append("【1人あたりの負担】")
        for name in members:
            lines.append(f"  {name}: {shares[name]:,}円")
    else:
        result = calculate_warikan(total, people)
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
        lines.append("【💸 送金プラン】")
        for t in transfers:
            lines.append(f"  {t.from_person} → {t.to_person}: {t.amount:,}円")

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

# メンバー設定: 「メンバー 田中 山田 鈴木」「メンバーは田中と山田と鈴木」
_MEMBER_PATTERN = re.compile(
    r"^(?:メンバー|めんばー|members?)\s*[はをの]?\s*(.+)$",
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


# 「田中がランチ1500円払った」「タクシー代2500円ね」のような自然言語
_NATURAL_RECORD_PATTERN = re.compile(
    r"^(?:(\S+?)[がは]\s*)?(.+?)([0-9,，]+)\s*(?:円|えん)",
    re.IGNORECASE,
)

# 「コンビニ 800」「タクシー 3000」のように円がなく、ラベル+数字だけ
_LABEL_AMOUNT_PATTERN = re.compile(
    r"^([^\d,，]{1,20})\s+([0-9,，]+)\s*(?:円|えん)?$",
    re.IGNORECASE,
)

# 「3000円 田中」「1500 田中」のように金額+支払者
_AMOUNT_PAYER_PATTERN = re.compile(
    r"^([0-9,，]+)\s*(?:円|えん)?\s+(\S+)$",
    re.IGNORECASE,
)

_INCOMPLETE_RECORD_PATTERN = re.compile(
    r"^(?:(\S+?)[がは]\s*)?(.+?)(?:を)?\s*(?:払った|支払った|出した|立て替えた|たてかえた)\s*$",
    re.IGNORECASE,
)

_INCOMPLETE_RECORD_COMMAND_PATTERN = re.compile(
    r"^(?:記録|きろく|add)\s+(.+)$",
    re.IGNORECASE,
)

# 対象者の抽出: 「田中と山田で」「田中、山田の分」部分（金額の後にくる名前リスト）
# 名前は非数字文字を含むことを要求
_PARTICIPANTS_SUFFIX = re.compile(
    r"[、,，\s]+([^\d,，\s]+(?:[と、,，][^\d,，\s]+)+)\s*(?:で|の分|分|の割り勘|で割り勘)?\s*$"
)

# 万・千の漢数字を含む金額パターン
_KANJI_AMOUNT_PATTERN = re.compile(
    r"(\d+)\s*万\s*(?:(\d+)\s*千)?|(\d+)\s*千"
)


def _parse_kanji_amount(text: str) -> Optional[int]:
    """「1万5千」「3千」「2万」のような漢数字金額をパース"""
    m = _KANJI_AMOUNT_PATTERN.search(text)
    if not m:
        return None
    if m.group(1):  # X万
        result = int(m.group(1)) * 10000
        if m.group(2):  # X万Y千
            result += int(m.group(2)) * 1000
        return result
    if m.group(3):  # X千
        return int(m.group(3)) * 1000
    return None


def _extract_participants(text: str) -> Optional[list[str]]:
    """テキスト末尾から対象者リストを抽出する。「田中と山田で」「田中、山田の分」など"""
    m = _PARTICIPANTS_SUFFIX.search(text)
    if not m:
        return None
    raw = m.group(1)
    names = re.split(r"[と、,，]+", raw)
    names = [re.sub(r"[での分]$", "", n).strip() for n in names]
    names = [n for n in names if n and not re.match(r"^[0-9,，]+$", n)]
    return names if len(names) >= 1 else None


@dataclass
class NaturalParseResult:
    """自然言語パースの結果"""
    amount: int
    label: str
    payer: Optional[str] = None
    participants: Optional[list[str]] = None


@dataclass
class IncompleteRecordParseResult:
    """未完成の支払い記録候補。足りない情報は確認フローで埋める。"""
    label: str
    payer: Optional[str] = None
    participants: Optional[list[str]] = None


def parse_natural_record_message(text: str) -> Optional[tuple[int, str, Optional[str]]]:
    """自然言語の支払い記録をパース。金額・ラベル・支払者を抽出。

    - 「ランチ1500円」→ (1500, "ランチ", None)
    - 「タクシー代2500円ね」→ (2500, "タクシー代", None)
    - 「田中がランチ1500円払った」→ (1500, "ランチ", "田中")
    - 「コンビニ 800」→ (800, "コンビニ", None)
    - 「3000円 田中」→ (3000, "支払い", "田中")
    - 「タクシー1万5千円」→ (15000, "タクシー", None)
    """
    result = parse_natural_record_extended(text)
    if result is None:
        return None
    return result.amount, result.label, result.payer


def parse_natural_record_extended(text: str) -> Optional[NaturalParseResult]:
    """自然言語の支払い記録をパース（対象者情報も含む拡張版）。

    - 「タクシー3000円 田中と山田で」→ NaturalParseResult(3000, "タクシー", None, ["田中", "山田"])
    - 「田中がランチ1500円払った」→ NaturalParseResult(1500, "ランチ", "田中", None)
    """
    t = text.strip()

    # ノイズ除去（末尾の「ね」「よ」「った」「だった」「です」「した」等）
    t_clean = re.sub(r"(?:だった|でした|払った|出した|立て替えた|ね|よ|な|だよ|です|だ)\s*[！!。]?\s*$", "", t).strip()

    # まず対象者を抽出（末尾から）
    participants = _extract_participants(t_clean)
    if participants:
        # 対象者部分を除去してからパース
        m_p = _PARTICIPANTS_SUFFIX.search(t_clean)
        if m_p:
            t_clean = t_clean[:m_p.start()].strip()

    # 漢数字金額を試す（「タクシー1万5千円」）
    kanji_amount = _parse_kanji_amount(t_clean)

    # パターン1: 「(支払者が)ラベル 金額円」
    m = _NATURAL_RECORD_PATTERN.match(t_clean)
    if m:
        payer_raw = m.group(1)
        label = m.group(2).strip() or "支払い"
        amount = kanji_amount or _clean_number(m.group(3))
        if amount > 0:
            payer = payer_raw if payer_raw and not _is_number_like(payer_raw) else None
            # ラベルが数字のみ（「3000円 田中」で「3」がラベルになるケース）を除外
            if not _is_number_like(label):
                return NaturalParseResult(amount, label, payer, participants)

    # パターン2: 「ラベル 数字」（円なし）: 「コンビニ 800」「タクシー 3000」
    m = _LABEL_AMOUNT_PATTERN.match(t_clean)
    if m:
        label = m.group(1).strip()
        amount = kanji_amount or _clean_number(m.group(2))
        if amount <= 0:
            return None
        # ラベルが「メンバー」等のキーワードなら除外
        if re.match(r"(?:メンバー|めんばー|members?|記録|きろく|リセット|ヘルプ)", label, re.IGNORECASE):
            return None
        return NaturalParseResult(amount, label, None, participants)

    # パターン3: 「金額 支払者名」: 「3000円 田中」「1500 田中」
    m = _AMOUNT_PAYER_PATTERN.match(t_clean)
    if m:
        amount = kanji_amount or _clean_number(m.group(1))
        payer = m.group(2)
        if amount <= 0:
            return None
        # 支払者名が「人」「名」「で」等なら除外
        if re.match(r"(?:人|名|で|を|の|円)$", payer):
            return None
        return NaturalParseResult(amount, "支払い", payer, participants)

    # 漢数字のみの場合: 「ランチ1万5千円」
    if kanji_amount and kanji_amount > 0:
        label_part = _KANJI_AMOUNT_PATTERN.sub("", t_clean)
        label_part = re.sub(r"[円えん]", "", label_part).strip()
        # 支払者を抽出
        payer = None
        payer_m = re.match(r"^(\S+?)[がは]\s*", label_part)
        if payer_m:
            payer = payer_m.group(1)
            label_part = label_part[payer_m.end():].strip()
        label_part = label_part or "支払い"
        return NaturalParseResult(kanji_amount, label_part, payer, participants)

    return None


def parse_incomplete_record_message(text: str) -> Optional[IncompleteRecordParseResult]:
    """支払いっぽいが金額が欠けている入力をパースする。"""
    t = text.strip()
    if not t:
        return None

    if _AMOUNT_PATTERN.search(t) or _parse_kanji_amount(t):
        return None

    t_clean = re.sub(r"(?:ね|よ|な|だよ|です|だ)\s*[！!。]?\s*$", "", t).strip()

    participants = _extract_participants(t_clean)
    if participants:
        m_p = _PARTICIPANTS_SUFFIX.search(t_clean)
        if m_p:
            t_clean = t_clean[:m_p.start()].strip()

    m = _INCOMPLETE_RECORD_PATTERN.match(t_clean)
    if m:
        payer_raw = m.group(1)
        label = (m.group(2) or "支払い").strip() or "支払い"
        if re.match(r"(?:メンバー|めんばー|members?|リセット|ヘルプ|精算)", label, re.IGNORECASE):
            return None
        payer = payer_raw if payer_raw and not _is_number_like(payer_raw) else None
        return IncompleteRecordParseResult(label=label, payer=payer, participants=participants)

    m = _INCOMPLETE_RECORD_COMMAND_PATTERN.match(t_clean)
    if not m:
        return None

    raw = m.group(1).strip()
    if not raw:
        return IncompleteRecordParseResult(label="支払い")

    tokens = re.split(r"\s+", raw)
    if len(tokens) >= 2:
        return IncompleteRecordParseResult(
            label=" ".join(tokens[1:]).strip() or "支払い",
            payer=tokens[0],
        )
    return IncompleteRecordParseResult(label=raw)


def parse_member_message(text: str) -> Optional[list[str]]:
    """「メンバー 田中 山田 鈴木」形式をパース。メンバーリストを返す。"""
    m = _MEMBER_PATTERN.match(text.strip())
    if m:
        raw = m.group(1)
        # スペース、カンマ、全角カンマ、読点、と、やで分割
        names = re.split(r"[,，、\s]+|(?<=\w)と(?=\w)|(?<=\w)や(?=\w)", raw.strip())
        names = [n for n in names if n]
        if names:
            return names
    return None
