"""跨模块会展引擎路由：执行历史、进度推进、配额视图等集成接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import exhibition, quota_package

exhibition_router = APIRouter(prefix="/api/exhibition", tags=["跨模块引擎"])


class PackageAreaPayload(BaseModel):
    """场馆面积更正/快照；只给 remaining 时按场馆可用面积反推已用。"""
    venue_area: float | None = None
    total_booth_area: float | None = None
    remaining: float | None = None
    booths: list[dict[str, Any]] | None = None
    note: str | None = None


class PackagePowerPayload(BaseModel):
    """功率核验结果；不传表示仍在核算。兼容单展位与整包两种结构。"""
    booth_no: str | None = None
    ok: bool | None = None
    design_load: float | None = None
    total_circuit_power: float | None = None
    over_draw: float | None = None
    circuits: list[dict[str, Any]] | None = None
    booths: list[dict[str, Any]] | None = None
    reason: str | None = None


class SavePackagePayload(BaseModel):
    venue_name: str
    area: PackageAreaPayload | None = None
    power: PackagePowerPayload | None = None
    operator: str = ""
    client_request_id: str | None = None
    package_no: str | None = None
    reason: str = "保存对账包"
    capture_power_live: bool = False


class CompletePackagePayload(BaseModel):
    power: PackagePowerPayload | None = None
    area: PackageAreaPayload | None = None
    operator: str = ""
    client_request_id: str | None = None


class PlacementPayload(BaseModel):
    booth_no: str
    slot_no: str = ""
    operator: str = ""
    client_request_id: str | None = None



@exhibition_router.get("/{booth_no}/history")
def booth_history(booth_no: str) -> dict:
    """展位执行历史：反查指定展位从规划到交场的全部事件。"""
    result = exhibition.booth_execution_history(booth_no)
    if result.get("booth") is None:
        raise HTTPException(status_code=404, detail=f"展位 {booth_no} 不存在")
    return result


@exhibition_router.post("/{booth_no}/advance")
def advance_construction(booth_no: str) -> dict:
    """推进布展进度节点（需要提供 node_id 参数）。"""
    booth = exhibition.store.find_booth(booth_no)
    if booth is None:
        raise HTTPException(status_code=404, detail=f"展位 {booth_no} 不存在")
    return {"booth": booth, "message": "请调用 POST /api/exhibition/advance/{node_id} 指定进度节点"}


@exhibition_router.post("/advance/{node_id}")
def advance_node(node_id: int) -> dict:
    """推进指定进度节点，含 DAG 拓扑前置校验和环检测。"""
    result = exhibition.topological_advance(node_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result


@exhibition_router.get("/quota")
def quota_overview() -> dict:
    """面积与功率配额综合结论：场馆容量、用电超载、排期冲突、DAG环检测。"""
    return exhibition.quota_summary()


@exhibition_router.get("/quota/venue/{venue_id}")
def venue_quota(venue_id: int) -> dict:
    """单个场馆的面积配额结论。"""
    result = exhibition.check_venue_capacity(venue_id)
    if not result.get("quota"):
        raise HTTPException(status_code=404, detail=result.get("reason", "场馆不存在"))
    return result


@exhibition_router.get("/quota/booth/{booth_no}")
def booth_power_quota(booth_no: str) -> dict:
    """单个展位的功率配额结论。"""
    result = exhibition.check_electrical_quota(booth_no)
    if not result.get("quota"):
        raise HTTPException(status_code=404, detail=result.get("reason", "展位不存在"))
    return result


# ---------- 配额对账包 ----------

def _raise_on_failure(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "对账包操作失败"))
    return result


@exhibition_router.post("/quota/packages")
def save_quota_package(payload: SavePackagePayload) -> dict:
    """保存配额对账包：面积占用 + 功率核验封成同一轮快照，不增加面积占用。

    支持 client_request_id 重试补偿；功率仍在核算时允许只存面积，返回核对未完成提示。
    """
    result = quota_package.save_package(
        payload.venue_name,
        area=payload.area.model_dump(exclude_none=True) if payload.area else None,
        power=payload.power.model_dump(exclude_none=True) if payload.power else None,
        operator=payload.operator,
        client_request_id=payload.client_request_id,
        package_no=payload.package_no,
        reason=payload.reason,
        capture_power_live=payload.capture_power_live,
    )
    return _raise_on_failure(result)


@exhibition_router.get("/quota/packages")
def list_quota_packages(
    venue_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict:
    """按场馆/状态回查对账包列表。"""
    packages = quota_package.list_packages(venue_name=venue_name, status=status)
    return {"items": packages, "total": len(packages)}


@exhibition_router.get("/quota/packages/latest")
def latest_quota_package(venue_name: str = Query(...)) -> dict:
    """场馆最近一次保存的对账包（刷新包号用）。"""
    package = quota_package.latest_package(venue_name)
    if package is None:
        raise HTTPException(status_code=404, detail=f"场馆 {venue_name} 暂无对账包")
    return package


@exhibition_router.get("/quota/packages/{package_no}")
def get_quota_package(package_no: str) -> dict:
    """主管凭包号回查：面积明细、功率明细、所依据的现场版本、采用轮次。"""
    package = quota_package.get_package(package_no)
    if package is None:
        raise HTTPException(status_code=404, detail=f"对账包 {package_no} 不存在")
    return package


@exhibition_router.get("/quota/packages/{package_no}/readiness")
def quota_package_readiness(package_no: str) -> dict:
    """只读核对结论：缺项时给提示，查询本身不阻断。"""
    result = quota_package.readiness(package_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason"))
    return result


@exhibition_router.post("/quota/packages/{package_no}/complete")
def complete_quota_package(package_no: str, payload: CompletePackagePayload) -> dict:
    """补齐功率核验：在新一轮里重新封存面积与功率，两者同轮后才可签发。"""
    result = quota_package.complete_package(
        package_no,
        power=payload.power.model_dump(exclude_none=True) if payload.power else None,
        area=payload.area.model_dump(exclude_none=True) if payload.area else None,
        operator=payload.operator,
        client_request_id=payload.client_request_id,
    )
    return _raise_on_failure(result)


@exhibition_router.post("/quota/packages/{package_no}/placements")
def issue_quota_placement(package_no: str, payload: PlacementPayload) -> dict:
    """凭对账包办理排位：缺项的包只能看提示，不能签发。"""
    result = quota_package.issue_placement(
        package_no,
        payload.booth_no,
        slot_no=payload.slot_no,
        operator=payload.operator,
        client_request_id=payload.client_request_id,
    )
    return _raise_on_failure(result)


@exhibition_router.get("/quota/packages/{package_no}/placements")
def list_quota_placements(package_no: str) -> dict:
    """按包号回查已签发的排位。"""
    placements = quota_package.list_placements(package_no)
    return {"items": placements, "total": len(placements)}



@exhibition_router.post("/checklist/{checklist_id}/signoff")
def checklist_signoff(checklist_id: int) -> dict:
    """验收签收：巡检通过才能签收验收项。"""
    validation = exhibition.validate_checklist_signoff(checklist_id)
    if not validation["ok"]:
        raise HTTPException(status_code=400, detail=validation["reason"])

    item = exhibition.store.find("checklist", checklist_id)
    item["status"] = "已确认"
    item["pending"] = False
    return {"ok": True, "reason": "签收完成", "item": item, "validation": validation}


@exhibition_router.post("/handover/{handover_id}/confirm")
def confirm_handover(handover_id: int) -> dict:
    """交场确认：验收清单全部签收才能交场。"""
    result = exhibition.do_handover(handover_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result


@exhibition_router.post("/change/{change_id}/issue")
def issue_change_order(change_id: int) -> dict:
    """签发变更指令：触发进度回退与重新验收传播。"""
    result = exhibition.propagate_change_order(change_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result


@exhibition_router.get("/conflicts")
def schedule_conflicts() -> dict:
    """运输排期冲突检测。"""
    conflicts = exhibition.detect_schedule_conflicts()
    return {"conflicts": conflicts, "count": len(conflicts)}


@exhibition_router.get("/dag/validate")
def dag_validate() -> dict:
    """DAG拓扑环检测与拓扑排序。"""
    nodes = exhibition.store.rows("construction")
    cycle = exhibition.detect_cycle(nodes)
    order = exhibition.build_dag_order(nodes) if cycle is None else []
    return {
        "cycle": cycle,
        "has_cycle": cycle is not None,
        "topological_order": order,
        "node_count": len(nodes),
    }


@exhibition_router.get("/safety/{booth_no}")
def safety_status(booth_no: str) -> dict:
    """展位安全巡检状态。"""
    return exhibition.check_safety_gate(booth_no)


# ---------- 跨模块关联查询路由 ----------

@exhibition_router.get("/booth/{booth_no}/venue")
def booth_venue(booth_no: str) -> dict:
    """展位→场馆关联查询。"""
    result = exhibition.booth_venue_info(booth_no)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@exhibition_router.get("/exhibitor/{exhibitor_id}/booth")
def exhibitor_booth(exhibitor_id: int) -> dict:
    """参展商→展位关联查询。"""
    result = exhibition.exhibitor_booth_info(exhibitor_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@exhibition_router.get("/design/{design_id}/booth")
def design_booth(design_id: int) -> dict:
    """设计→展位关联查询。"""
    result = exhibition.design_booth_info(design_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@exhibition_router.get("/material/{material_id}/design")
def material_design(material_id: int) -> dict:
    """物料→设计关联查询。"""
    result = exhibition.material_design_info(material_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@exhibition_router.get("/incident/{incident_id}/venue")
def incident_venue(incident_id: int) -> dict:
    """事件→场馆关联查询。"""
    result = exhibition.incident_venue_info(incident_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@exhibition_router.get("/handover/{handover_id}/schedule")
def handover_schedule(handover_id: int) -> dict:
    """交场→排期关联查询。"""
    result = exhibition.handover_schedule_info(handover_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@exhibition_router.get("/booth/{booth_no}/cross-snapshot")
def cross_snapshot(booth_no: str) -> dict:
    """展位跨模块全局快照。"""
    result = exhibition.cross_module_snapshot(booth_no)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result