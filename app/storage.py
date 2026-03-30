"""グループセッションのストレージ。

デフォルトではファイル永続化を有効にし、サーバー再起動後も記録を復元する。
pytest 実行中はテストの独立性を優先して永続化を無効にする。
"""
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from app.warikan import GroupSession, Payment

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


def _storage_path() -> Path:
    return Path(os.environ.get("WARIKAN_STORAGE_PATH", ".data/warikan_store.json"))


def _persistence_enabled() -> bool:
    if os.environ.get("WARIKAN_DISABLE_PERSISTENCE") == "1":
        return False
    if os.environ.get("WARIKAN_ENABLE_PERSISTENCE") == "1":
        return True
    return "pytest" not in sys.modules


def _serialize_session(session: GroupSession) -> dict:
    return {
        "payments": [asdict(payment) for payment in session.payments],
        "members": list(session.members),
    }


def _serialize_wizard(wizard: WizardState) -> dict:
    return {
        "wizard_type": wizard.wizard_type,
        "step": wizard.step,
        "data": wizard.data,
    }


def persist_state() -> None:
    """現在の状態をファイルに保存する。"""
    if not _persistence_enabled():
        return

    path = _storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sessions": {group_id: _serialize_session(session) for group_id, session in _sessions.items()},
        "people": _people,
        "wizards": {group_id: _serialize_wizard(wizard) for group_id, wizard in _wizards.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _load_state() -> None:
    if not _persistence_enabled():
        return

    path = _storage_path()
    if not path.exists():
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    _sessions.clear()
    for group_id, session_data in payload.get("sessions", {}).items():
        session = GroupSession()
        session.members = list(session_data.get("members", []))
        session.payments = [Payment(**payment) for payment in session_data.get("payments", [])]
        _sessions[group_id] = session

    _people.clear()
    _people.update({str(k): int(v) for k, v in payload.get("people", {}).items()})

    _wizards.clear()
    for group_id, wizard_data in payload.get("wizards", {}).items():
        _wizards[group_id] = WizardState(
            wizard_type=wizard_data.get("wizard_type", "record"),
            step=wizard_data.get("step", "amount"),
            data=wizard_data.get("data", {}),
        )


def get_session(group_id: str) -> GroupSession:
    if group_id not in _sessions:
        _sessions[group_id] = GroupSession()
        persist_state()
    return _sessions[group_id]


def reset_session(group_id: str) -> None:
    _sessions[group_id] = GroupSession()
    _people.pop(group_id, None)
    _wizards.pop(group_id, None)
    persist_state()


def get_people(group_id: str) -> Optional[int]:
    return _people.get(group_id)


def set_people(group_id: str, people: int) -> None:
    _people[group_id] = people
    persist_state()


def get_wizard(group_id: str) -> Optional[WizardState]:
    return _wizards.get(group_id)


def set_wizard(group_id: str, wizard: WizardState) -> None:
    _wizards[group_id] = wizard
    persist_state()


def clear_wizard(group_id: str) -> None:
    _wizards.pop(group_id, None)
    persist_state()


_load_state()
