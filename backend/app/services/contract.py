"""委托合同业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "contract"
REQUIRED_FIELDS = ["合同编号", "委托单位", "联系人"]
STATUS_ORDER = ["待签约", "执行中", "已完成", "已终止"]
ACTION_RULES = {"签约合同": "执行中", "终止合同": "已终止", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []
UNIQUE_FIELD = "合同编号"  # 同一份委托检验合同只认这个来源标识，重复提交与冲突都按它归并
STATUS_FIELD = "合同状态"  # 列表展示的状态列，处理结果必须同步回写，列表与详情才是同一份结果


def _sync_status(row: dict[str, Any]) -> None:
    """把处理结果回写到列表展示列；旧数据里残留的旧提示一并覆盖对齐。"""
    status = row.get("status")
    if status and row.get(STATUS_FIELD) != status:
        row[STATUS_FIELD] = status


class ContractService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for row in rows:
            _sync_status(row)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(UNIQUE_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            _sync_status(entry)
        return entry

    def find_by_number(self, contract_no: str) -> dict[str, Any] | None:
        """按合同编号定位同一份委托检验合同：重复登记、冲突合并都靠它找到同一个来源。"""
        for row in store.rows(MODULE):
            if str(row.get(UNIQUE_FIELD, "")).strip() == contract_no:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        contract_no = str(values.get(UNIQUE_FIELD) or "").strip()
        existing = self.find_by_number(contract_no)
        if existing is not None:
            # 重复结果拦截：同一合同编号只保留一份记录，本次提交覆盖旧数据，不再累积新条目
            for field in REQUIRED_FIELDS:
                existing[field] = values.get(field)
            _sync_status(existing)
            return existing, [], False
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry[STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], True

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"委托检验合同 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于委托合同可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry.get("status") == target:
            # 重复提交拦截：已处于目标状态，只对齐回写，不再产生第二份处理结果
            _sync_status(entry)
            return entry, f"委托检验合同已处于「{target}」，重复的「{action}」已被拦截"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        _sync_status(entry)
        return entry, f"委托检验合同已{action}"
