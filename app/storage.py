"""グループセッションのインメモリストレージ"""
from typing import Optional

from app.warikan import GroupSession

# group_id -> GroupSession
_sessions: dict[str, GroupSession] = {}

# group_id -> 設定中の人数
_people: dict[str, int] = {}


def get_session(group_id: str) -> GroupSession:
    if group_id not in _sessions:
        _sessions[group_id] = GroupSession()
    return _sessions[group_id]


def reset_session(group_id: str) -> None:
    _sessions[group_id] = GroupSession()
    _people.pop(group_id, None)


def get_people(group_id: str) -> Optional[int]:
    return _people.get(group_id)


def set_people(group_id: str, people: int) -> None:
    _people[group_id] = people
