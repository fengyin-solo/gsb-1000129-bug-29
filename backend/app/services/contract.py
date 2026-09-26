"""委托合同业务规则：状态流转、字段校验、筛选口径与处理结果回写都收在这里。

处理结果的口径很重要：
- 每份合同只内嵌「一份」有效处理结果（entry["处理结果"]），列表与详情读的是同一条
  entry，因此两边永远是同一份数据，不会出现列表多一条、详情还是旧提示的情况；
- 同一来源（clientToken）的重复提交按幂等处理，直接回首次结果，不再追加、不累积；
- 提交携带的 revision 落后于服务器时判为冲突，返回新老两条结果供比对，确认后才能覆盖。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "contract"
REQUIRED_FIELDS = ["合同编号", "委托单位", "联系人"]
STATUS_ORDER = ["待签约", "执行中", "已完成", "已终止"]
ACTION_RULES = {"签约合同": "执行中", "终止合同": "已终止", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []

# 处理结果只接受这几种结论；「无处理结果」用 None 表示，绝不另起一条空记录占位。
RESULT_OUTCOMES = ["合格", "不合格", "退回补充"]
# 处理完成后合同对应的状态；处理与合同状态在这里一并回写，避免只改一半。
RESULT_STATUS = "已完成"


class ConflictError(Exception):
    """提交依据的版本已过期：调用方需要比对新老两条结果后决定是否覆盖。"""

    def __init__(
        self,
        message: str,
        *,
        submitted: dict[str, Any] | None,
        current: dict[str, Any] | None,
        server_revision: int,
    ) -> None:
        super().__init__(message)
        self.message = message
        # 冲突「前」：本次提交所依据的、客户端手里的旧处理结果。
        self.submitted = submitted
        # 冲突「后」：服务器上已经生效的最新处理结果。
        self.current = current
        self.server_revision = server_revision


def _active_result(entry: dict[str, Any]) -> dict[str, Any] | None:
    """读取一份合同当前唯一有效的处理结果；没有处理结果时返回 None。"""
    result = entry.get("处理结果")
    return result if isinstance(result, dict) else None


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
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("合同编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 每份合同从一开始就只有「一份」处理结果槽位，初值为空，绝不预置占位记录。
        entry["revision"] = 0
        entry["处理结果"] = None
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"委托检验合同 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于委托合同可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"委托检验合同已{action}"

    def submit_result(
        self,
        entry_id: int,
        values: dict[str, Any],
        *,
        force: bool = False,
    ) -> tuple[dict[str, Any] | None, str, str]:
        """提交或覆盖一份合同的处理结果。

        返回 (entry, message, outcome)，outcome 取值：
        - "created"  首次写入；
        - "replaced" 确认覆盖冲突后的旧结果；
        - "duplicate" 同一来源重复提交，原样返回首次结果，不做任何改动。
        版本过期且未显式 force 时抛 ConflictError。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"委托检验合同 {entry_id} 不存在或已归档", "error"

        conclusion = str(values.get("处理结果") or values.get("conclusion") or "").strip()
        if conclusion not in RESULT_OUTCOMES:
            return None, f"处理结果须为 {'、'.join(RESULT_OUTCOMES)} 之一", "error"
        remark = str(values.get("备注") or values.get("remark") or "").strip()
        inspector = str(values.get("检验员") or values.get("inspector") or "").strip()

        # revision 缺省按「尚无处理结果」处理；前端首次提交时传 0 或不传均可。
        try:
            base_revision = int(values.get("revision", 0))
        except (TypeError, ValueError):
            return None, "提交的版本号不是合法整数，请刷新详情后重试", "error"
        if base_revision < 0:
            return None, "提交的版本号不能为负数", "error"

        token = str(values.get("clientToken") or "").strip()
        current = _active_result(entry)
        server_revision = int(entry.get("revision", 0))

        # 幂等拦截：同一来源（clientToken）已经写入过，就把首次结果原样还回去，
        # 不再追加第二条、不推进版本、不刷新时间——重复点击/网络重试都安全。
        if current is not None and token and token == current.get("clientToken"):
            return entry, "处理结果已接收，请勿重复提交（已返回首次结果）", "duplicate"

        # 乐观并发：手里的版本落后于服务器，说明已经有另一份结果先落库了。
        # 把冲突前后两条结果一起带回去供比对，除非显式确认覆盖（force）。
        if current is not None and base_revision != server_revision and not force:
            submitted_view = self._build_candidate(
                entry, conclusion, remark, inspector, token, base_revision
            )
            raise ConflictError(
                "该委托合同已有更新的处理结果，请核对新旧两条记录后确认是否覆盖",
                submitted=submitted_view,
                current=current,
                server_revision=server_revision,
            )

        is_replace = current is not None
        result = self._build_candidate(
            entry, conclusion, remark, inspector, token, server_revision + 1
        )

        # 关键：直接覆盖唯一的处理结果槽位，而不是 append 一条。
        # 列表与详情都从同一个 entry 取这一份，天然保持一致、不会累积。
        entry["处理结果"] = result
        entry["revision"] = server_revision + 1
        # 处理结果一旦落库，合同同步进入「已完成」，保证状态与结果是同一份事实。
        entry["status"] = RESULT_STATUS
        entry["pending"] = False
        entry["abnormal"] = conclusion == "不合格"

        if is_replace:
            return entry, "已用本次处理结果覆盖旧记录，当前仅保留一份有效结果", "replaced"
        return entry, "委托检验合同处理结果已提交", "created"

    @staticmethod
    def _build_candidate(
        entry: dict[str, Any],
        conclusion: str,
        remark: str,
        inspector: str,
        token: str,
        revision: int,
    ) -> dict[str, Any]:
        """构造一份待写入/待比对的处理结果快照。"""
        return {
            "合同编号": entry.get("合同编号"),
            "委托单位": entry.get("委托单位"),
            "处理结果": conclusion,
            "备注": remark,
            "检验员": inspector,
            "clientToken": token,
            "revision": revision,
            "处理时间": _now_text(),
        }


def _now_text() -> str:
    """生成处理时间文本；放在模块级函数里便于测试时打桩。"""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
