"""グループセッションのインメモリストレージ"""
from dataclasses import dataclass, field
from typing import Optional

from app.warikan import GroupSession

# group_id -> GroupSession
_sessions: dict[str, GroupSession] = {}

# group_id -> 設定中の人数
_people: dict[str, int] = {}


@dataclass
class WizardState:
    """ステップ入力ウィザードの状態"""
    wizard_type: str  # "record" | "warikan"
    step: str         # 現在のステップ名
    data: dict = field(default_factory=dict)  # 入力済みデータ


# group_id -> WizardState
_wizards: dict[str, WizardState] = {}


def get_session(group_id: str) -> GroupSession:
    if group_id not in _sessions:
        _sessions[group_id] = GroupSession()
    return _sessions[group_id]


def reset_session(group_id: str) -> None:
    _sessions[group_id] = GroupSession()
    _people.pop(group_id, None)
    _wizards.pop(group_id, None)


def get_people(group_id: str) -> Optional[int]:
    return _people.get(group_id)


def set_people(group_id: str, people: int) -> None:
    _people[group_id] = people


def get_wizard(group_id: str) -> Optional[WizardState]:
    return _wizards.get(group_id)


def set_wizard(group_id: str, wizard: WizardState) -> None:
    _wizards[group_id] = wizard


def clear_wizard(group_id: str) -> None:
    _wizards.pop(group_id, None)
