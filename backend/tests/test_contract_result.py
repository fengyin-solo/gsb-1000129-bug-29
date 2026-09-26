"""委托检验合同处理结果：回写同源、重复拦截与冲突覆盖的回归测试。

直接对内存 store 的服务层做断言，避免依赖网络；覆盖：
- 首次写入后列表与详情是同一份处理结果、不会多出记录；
- 同一来源（clientToken）重复提交幂等，不新增、不累积、不推进版本；
- 版本落后判冲突，返回冲突前后两条记录，且冲突本身不改数据；
- 确认覆盖（force）后旧数据被替换、仅保留一份有效结果；
- 覆盖作为一次新写入（新令牌），其网络重试不会误回退到被覆盖的旧结果；
- 继续在最新版本上提交，始终只有一份有效状态。
"""
from __future__ import annotations

import pytest

from app.services.contract import ConflictError, ContractService, _active_result
from app.store import store


@pytest.fixture()
def service() -> ContractService:
    store._tables["contract"] = [
        {
            "id": 1,
            "status": "待签约",
            "pending": True,
            "abnormal": False,
            "revision": 0,
            "处理结果": None,
            "合同编号": "CONT-T1",
            "委托单位": "某委托单位",
            "联系人": "甲",
        }
    ]
    return ContractService()


def _submit(service: ContractService, **overrides):
    values = {
        "处理结果": "合格",
        "检验员": "张三",
        "备注": "首次",
        "revision": 0,
        "clientToken": "T-A",
    }
    values.update(overrides)
    return service.submit_result(1, values, force=bool(values.get("force")))


def test_first_submit_writes_single_result_shared_by_list_and_detail(service: ContractService) -> None:
    entry, message, outcome = _submit(service)
    assert outcome == "created"
    assert entry["revision"] == 1
    assert entry["status"] == "已完成"
    assert _active_result(entry)["处理结果"] == "合格"

    listed, total = service.list_entries()
    detail = service.get_entry(1)
    assert total == 1
    # 列表行与详情是同一个 dict，处理结果字段必然同源。
    assert listed[0] is detail
    assert listed[0]["处理结果"] == detail["处理结果"] == entry["处理结果"]


def test_duplicate_same_source_is_idempotent(service: ContractService) -> None:
    entry1, _, _ = _submit(service)
    first = dict(entry1["处理结果"])

    # 同 token 重复点击/网络重试，哪怕带了不同内容，也只回首次结果。
    entry2, message, outcome = _submit(service, 处理结果="不合格", 备注="重复", revision=1)
    assert outcome == "duplicate"
    assert "请勿重复提交" in message
    assert entry2["revision"] == 1
    assert entry2["处理结果"] == first
    assert service.list_entries()[1] == 1  # 不累积


def test_stale_revision_conflicts_and_returns_both_records_without_writing(service: ContractService) -> None:
    _submit(service)

    with pytest.raises(ConflictError) as exc:
        _submit(service, 处理结果="不合格", 备注="旧版本", revision=0, clientToken="T-B")

    err = exc.value
    # 冲突「前」是本次想写入的旧版本，冲突「后」是服务器最新结果，来源同为 CONT-T1。
    assert err.submitted["合同编号"] == err.current["合同编号"] == "CONT-T1"
    assert err.submitted["备注"] == "旧版本"
    assert err.current["处理结果"] == "合格"
    assert err.server_revision == 1

    detail = service.get_entry(1)
    assert detail["revision"] == 1
    assert _active_result(detail)["处理结果"] == "合格"


def test_force_overwrite_replaces_old_result_with_single_effective_state(service: ContractService) -> None:
    _submit(service)
    with pytest.raises(ConflictError):
        _submit(service, revision=0, clientToken="T-B")

    entry, message, outcome = _submit(
        service, 处理结果="不合格", 备注="确认覆盖", revision=1, clientToken="T-B", force=True
    )
    assert outcome == "replaced"
    assert entry["revision"] == 2
    assert _active_result(entry)["处理结果"] == "不合格"
    assert entry["abnormal"] is True
    assert service.list_entries()[1] == 1  # 仍然只有一份，没有新增第二条
    assert service.get_entry(1)["处理结果"] == entry["处理结果"]


def test_overwrite_retry_with_fresh_token_does_not_restore_old_result(service: ContractService) -> None:
    _submit(service)
    # 覆盖使用一次性新令牌，模拟该覆盖请求的网络重试（同新令牌）。
    values = {
        "处理结果": "不合格",
        "备注": "覆盖",
        "revision": 1,
        "clientToken": "T-B::override::1",
        "force": True,
    }
    entry1, _, outcome1 = service.submit_result(1, values, force=True)
    assert outcome1 == "replaced"
    entry2, _, outcome2 = service.submit_result(1, dict(values), force=True)
    # 重试应幂等命中「覆盖后的」这份，而不是退回被覆盖掉的「合格」。
    assert outcome2 == "duplicate"
    assert _active_result(entry2)["处理结果"] == "不合格"
    assert entry2["revision"] == 2


def test_continue_submitting_keeps_single_valid_state(service: ContractService) -> None:
    _submit(service)
    entry, _, _ = _submit(
        service, 处理结果="退回补充", 备注="继续提交", revision=1, clientToken="T-C"
    )
    assert entry["revision"] == 2
    assert _active_result(entry)["处理结果"] == "退回补充"
    listed, total = service.list_entries()
    assert total == 1
    assert listed[0]["处理结果"] == service.get_entry(1)["处理结果"]


def test_invalid_conclusion_rejected(service: ContractService) -> None:
    entry, message, outcome = _submit(service, 处理结果="随便")
    assert entry is None and outcome == "error"
    assert service.get_entry(1)["revision"] == 0
    assert _active_result(service.get_entry(1)) is None
