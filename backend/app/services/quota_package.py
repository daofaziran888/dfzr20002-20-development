"""配额对账包：把面积占用与功率核验封成同一轮快照，供展位编排复核和排位签发。

核心约定：
- 一个对账包是一份只读快照，保存它不会登记展位、不会增加任何面积占用。
- 面积和功率只有落在同一轮（round）里才算「核对完成」，半成品只能查看不能签发。
- 场馆后续更正不会改写已经封存的轮次；补齐缺失项时会在新一轮里重新封存当前面积，
  因此最终签发采用的是补齐时那一轮的面积，而不是最早写入的旧余量。
- 保存/签发都接受 client_request_id；响应中断后重试拿回同一个包号，不会重复建包。
"""
from __future__ import annotations

import copy
import time
from typing import Any

from app.store import store

PACKAGE_MODULE = "quota_package"
PLACEMENT_MODULE = "placement"

STATUS_INCOMPLETE = "核对未完成"
STATUS_COMPLETE = "核对完成"

PART_AREA = "面积占用"
PART_POWER = "功率核验"


# ---------- 通用解析 ----------

def _num(value: Any) -> float:
    """把 28 / '28' / '28㎡' / '12 kW' 这类现场写法解析成数字。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value if value is not None else "0")
    for token in ("平米", "㎡", "m²", "kW", "KW", "kw", "W", ",", " "):
        text = text.replace(token, "")
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return 0.0


def _now() -> float:
    return time.time()


def _today() -> str:
    return time.strftime("%Y%m%d", time.localtime())


def _find_venue(venue_name: str) -> dict[str, Any] | None:
    for venue in store.rows("venue"):
        if str(venue.get("场馆名称", "")) == venue_name:
            return venue
    return None


def _venue_booths(venue_name: str) -> list[dict[str, Any]]:
    return [b for b in store.rows("booth") if str(b.get("所属区域", "")) == venue_name]


# ---------- 现场版本 ----------

def source_versions(venue_name: str) -> dict[str, Any]:
    """记录本轮快照所依据的现场版本（场馆/展位/设计/用电）。"""
    venue = _find_venue(venue_name)
    booths = _venue_booths(venue_name)
    booth_nos = {str(b.get("展位编号", "")) for b in booths}
    designs = [d for d in store.rows("design") if str(d.get("备注说明", "")) in booth_nos]
    electricals = [e for e in store.rows("electrical") if str(e.get("所属展位", "")) in booth_nos]
    versions = {
        "venue": {
            "name": venue_name,
            "id": venue.get("id") if venue else None,
            "version": str(venue.get("生效版本", "")) if venue else "",
        },
        "booths": sorted(
            [{"booth_no": str(b.get("展位编号", "")), "version": str(b.get("生效版本", ""))}
             for b in booths],
            key=lambda item: item["booth_no"],
        ),
        "designs": sorted(
            [{"booth_no": str(d.get("备注说明", "")), "version": str(d.get("生效版本", ""))}
             for d in designs],
            key=lambda item: item["booth_no"],
        ),
        "electrical": sorted(
            [{"circuit": str(e.get("回路编号", "")), "booth_no": str(e.get("所属展位", "")),
              "version": str(e.get("生效版本", ""))}
             for e in electricals],
            key=lambda item: item["circuit"],
        ),
    }
    distinct = {str(v) for v in [versions["venue"]["version"]] if v}
    distinct |= {b["version"] for b in versions["booths"] if b["version"]}
    distinct |= {d["version"] for d in versions["designs"] if d["version"]}
    distinct |= {e["version"] for e in versions["electrical"] if e["version"]}
    versions["version_set"] = sorted(distinct)
    return versions


# ---------- 面积快照 ----------

def capture_area(venue_name: str, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """采集面积占用：默认按场馆内展位实时核算，也可写入场馆送来的更正数值。

    只读，不登记展位、不改变任何占用。
    """
    venue = _find_venue(venue_name)
    if venue is None:
        return {"ok": False, "reason": f"场馆 {venue_name} 不存在", "venue_name": venue_name}

    venue_area = _num(venue.get("可用面积"))
    booths = _venue_booths(venue_name)
    booth_details: list[dict[str, Any]] = []
    total_booth_area = 0.0
    for booth in booths:
        area = _num(booth.get("面积尺寸"))
        total_booth_area += area
        booth_details.append({
            "booth_no": str(booth.get("展位编号", "")),
            "area": area,
            "status": str(booth.get("status", "")),
        })

    remaining = venue_area - total_booth_area
    corrected_from: float | None = None

    if override:
        # 场馆更正：允许只给出新的余量，其余口径沿用采集值。
        corrected_from = remaining
        if "venue_area" in override:
            venue_area = _num(override.get("venue_area"))
        if "total_booth_area" in override:
            total_booth_area = _num(override.get("total_booth_area"))
        if "remaining" in override:
            remaining = _num(override.get("remaining"))
        else:
            remaining = venue_area - total_booth_area
        if override.get("booths") is not None:
            booth_details = copy.deepcopy(override.get("booths") or [])
        override_note = str(override.get("note", "")).strip()
    else:
        override_note = ""

    ok = remaining >= 0
    result = {
        "ok": ok,
        "venue_name": venue_name,
        "venue_area": venue_area,
        "total_booth_area": total_booth_area,
        "remaining": remaining,
        "booths": booth_details,
        "reason": "" if ok else f"展位总面积 {total_booth_area}㎡ 超过场馆可用面积 {venue_area}㎡",
    }
    if corrected_from is not None:
        result["corrected_from_remaining"] = corrected_from
        result["correction"] = True
        result["correction_note"] = override_note or "场馆送来面积更正"
    return result


# ---------- 功率快照 ----------

def capture_power(
    venue_name: str | None = None,
    booth_nos: list[str] | None = None,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """采集功率核验：逐展位对比设计负荷与用电回路总功率。

    override 可以直接给入核算结果（例如现场仍在核算时由外部送回）。
    """
    if override:
        return _normalize_power(override)

    if booth_nos is None:
        if not venue_name:
            return {"ok": False, "reason": "缺少场馆或展位范围"}
        booth_nos = [str(b.get("展位编号", "")) for b in _venue_booths(venue_name)]

    booth_results: list[dict[str, Any]] = []
    total_load = 0.0
    total_power = 0.0
    for booth_no in booth_nos:
        booth = store.find_booth(booth_no)
        if booth is None:
            booth_results.append({
                "booth_no": booth_no, "ok": False, "design_load": 0.0,
                "total_circuit_power": 0.0, "over_draw": 0.0, "circuits": [],
                "reason": f"展位 {booth_no} 不存在",
            })
            continue
        design_load = 0.0
        for design in store.rows("design"):
            if str(design.get("备注说明", "")) == booth_no:
                design_load = _num(design.get("用电负荷"))
                break
        circuits = []
        total_circuit = 0.0
        for circuit in store.booth_electrical(booth_no):
            power = _num(circuit.get("额定功率"))
            total_circuit += power
            circuits.append({
                "circuit_id": str(circuit.get("回路编号", "")),
                "power": power,
                "status": str(circuit.get("status", "")),
            })
        over = max(total_circuit - design_load, 0.0)
        ok = not (design_load > 0 and total_circuit > design_load)
        booth_results.append({
            "booth_no": booth_no,
            "ok": ok,
            "design_load": design_load,
            "total_circuit_power": total_circuit,
            "over_draw": over,
            "circuits": circuits,
            "reason": "" if ok else
            f"用电回路总功率 {total_circuit}kW 超过展位 {booth_no} 的设计负荷 {design_load}kW",
        })
        total_load += design_load
        total_power += total_circuit

    return {
        "ok": all(item["ok"] for item in booth_results),
        "booths": booth_results,
        "total_design_load": total_load,
        "total_circuit_power": total_power,
        "over_draw": max(total_power - total_load, 0.0),
        "reason": "" if all(item["ok"] for item in booth_results)
        else "存在展位用电回路超过设计负荷",
    }


def _normalize_power(power: dict[str, Any]) -> dict[str, Any]:
    """接受单个展位结果或整包结果，统一成与 capture_power 相同的结构。"""
    data = copy.deepcopy(power)
    if "booths" not in data:
        booth_item = {
            "booth_no": str(data.get("booth_no", "")),
            "ok": bool(data.get("ok", True)),
            "design_load": _num(data.get("design_load")),
            "total_circuit_power": _num(data.get("total_circuit_power")),
            "over_draw": _num(data.get("over_draw")),
            "circuits": copy.deepcopy(data.get("circuits") or []),
            "reason": str(data.get("reason", "")),
        }
        data = {
            "booths": [booth_item],
            "total_design_load": booth_item["design_load"],
            "total_circuit_power": booth_item["total_circuit_power"],
            "over_draw": booth_item["over_draw"],
            "ok": booth_item["ok"],
            "reason": booth_item["reason"],
        }
    else:
        data.setdefault("ok", all(bool(item.get("ok", True)) for item in data.get("booths", [])))
        data.setdefault("total_design_load",
                        sum(_num(item.get("design_load")) for item in data.get("booths", [])))
        data.setdefault("total_circuit_power",
                        sum(_num(item.get("total_circuit_power")) for item in data.get("booths", [])))
        data.setdefault("over_draw",
                        max(_num(data["total_circuit_power"]) - _num(data["total_design_load"]), 0.0))
        data.setdefault("reason", "" if data["ok"] else "存在展位用电回路超过设计负荷")
    return data


# ---------- 包内辅助 ----------

def _missing_parts(package: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not package.get("area"):
        missing.append(PART_AREA)
    if not package.get("power"):
        missing.append(PART_POWER)
    return missing


def _refresh_status(package: dict[str, Any]) -> None:
    missing = _missing_parts(package)
    package["missing"] = missing
    package["status"] = STATUS_INCOMPLETE if missing else STATUS_COMPLETE
    package["pending"] = package["status"] != STATUS_COMPLETE
    package["abnormal"] = False
    if missing:
        package["warning"] = f"核对未完成：缺少{'、'.join(missing)}，当前不能作为排位签发依据"
    else:
        package["warning"] = ""


def _find_package(package_no: str) -> dict[str, Any] | None:
    for package in store.rows(PACKAGE_MODULE):
        if str(package.get("package_no", "")) == package_no:
            return package
    return None


def _find_by_request_id(client_request_id: str | None) -> dict[str, Any] | None:
    if not client_request_id:
        return None
    for package in store.rows(PACKAGE_MODULE):
        if client_request_id in package.get("client_request_ids", []):
            return package
    return None


def _open_package_for(venue_name: str) -> dict[str, Any] | None:
    candidates = [
        p for p in store.rows(PACKAGE_MODULE)
        if str(p.get("venue_name", "")) == venue_name and p.get("status") != STATUS_COMPLETE
    ]
    return candidates[-1] if candidates else None


def _last_round(package: dict[str, Any]) -> dict[str, Any] | None:
    rounds = package.get("rounds") or []
    return rounds[-1] if rounds else None


def _make_round(
    round_no: int,
    area: dict[str, Any] | None,
    power: dict[str, Any] | None,
    versions: dict[str, Any],
    operator: str,
    reason: str,
) -> dict[str, Any]:
    complete = area is not None and power is not None
    return {
        "round_no": round_no,
        "captured_at": _now(),
        "area": copy.deepcopy(area) if area else None,
        "power": copy.deepcopy(power) if power else None,
        "source_versions": copy.deepcopy(versions),
        "operator": operator,
        "reason": reason,
        "complete": complete,
        "missing": [] if complete else (
            [PART_AREA] * (area is None) + [PART_POWER] * (power is None)
        ),
    }


def _apply_round(package: dict[str, Any], round_data: dict[str, Any]) -> None:
    """把新一轮快照写入包，并维护「当前采用」口径。"""
    previous_area = copy.deepcopy(package.get("area"))
    previous_area_round = package.get("area_round")
    previous_power = copy.deepcopy(package.get("power"))

    package.setdefault("rounds", []).append(round_data)

    if round_data.get("area"):
        package["area"] = copy.deepcopy(round_data["area"])
        package["area_round"] = round_data["round_no"]
    if round_data.get("power"):
        package["power"] = copy.deepcopy(round_data["power"])
        package["power_round"] = round_data["round_no"]
    package["source_versions"] = copy.deepcopy(round_data["source_versions"])
    package["updated_at"] = round_data["captured_at"]

    if round_data.get("complete"):
        # 只有同一轮里同时具备面积和功率，才成为签发依据。
        if previous_area and (
            _num(previous_area.get("remaining")) != _num(round_data["area"].get("remaining"))
            or _num(previous_area.get("venue_area")) != _num(round_data["area"].get("venue_area"))
            or _num(previous_area.get("total_booth_area")) != _num(round_data["area"].get("total_booth_area"))
        ):
            package.setdefault("superseded_areas", []).append({
                "round_no": previous_area_round,
                "remaining": _num(previous_area.get("remaining")),
                "venue_area": _num(previous_area.get("venue_area")),
                "total_booth_area": _num(previous_area.get("total_booth_area")),
                "reason": (
                    "被补齐功率时重新封存的一轮面积取代"
                    if previous_power is None else "被新一轮封存面积取代"
                ),
            })
        package["adopted_round"] = round_data["round_no"]
        package["adopted_area"] = copy.deepcopy(round_data["area"])
        package["adopted_power"] = copy.deepcopy(round_data["power"])
        package["adopted_at"] = round_data["captured_at"]
        package["area_source_round"] = round_data.get("area_source_round",
                                                       round_data["round_no"])
        package["status"] = STATUS_COMPLETE
    else:
        package["status"] = STATUS_INCOMPLETE
    _refresh_status(package)


def _public_view(package: dict[str, Any]) -> dict[str, Any]:
    """给看板/主管回查用的完整视图：两项明细 + 现场版本 + 采用口径。"""
    adopted = package.get("adopted_round") is not None
    area = package.get("adopted_area") or package.get("area")
    power = package.get("adopted_power") or package.get("power")
    view = copy.deepcopy(package)
    view["area_detail"] = copy.deepcopy(area)
    view["power_detail"] = copy.deepcopy(power)
    view["area_detail_adopted"] = adopted and package.get("adopted_area") is not None
    view["power_detail_adopted"] = adopted and package.get("adopted_power") is not None
    view["self_area_occupancy"] = 0.0
    view["placement_ready"] = package.get("status") == STATUS_COMPLETE
    view["source_versions"] = copy.deepcopy(package.get("source_versions") or {})
    view["adopted"] = {
        "round_no": package.get("adopted_round"),
        "area_remaining": _num(package.get("adopted_area", {}).get("remaining"))
        if package.get("adopted_area") else None,
        "area_venue_area": _num(package.get("adopted_area", {}).get("venue_area"))
        if package.get("adopted_area") else None,
        "total_circuit_power": _num(package.get("adopted_power", {}).get("total_circuit_power"))
        if package.get("adopted_power") else None,
        "sealed_at": package.get("adopted_at"),
    }
    view["superseded_areas"] = copy.deepcopy(package.get("superseded_areas") or [])
    view["self_area_note"] = "对账包为只读快照，不登记展位，不增加面积占用"
    return view


# ---------- 保存 / 回查 ----------

def save_package(
    venue_name: str,
    area: dict[str, Any] | None = None,
    power: dict[str, Any] | None = None,
    *,
    operator: str = "",
    client_request_id: str | None = None,
    package_no: str | None = None,
    reason: str = "保存对账包",
    capture_power_live: bool = False,
) -> dict[str, Any]:
    """保存配额对账包。

    同一 client_request_id 的重试直接返回原包（响应中断后的补偿）；
    同一场馆已有未完成包时，把新快照作为下一轮追加，包号保持不变。
    ``capture_power_live`` 表示不传功率值时按场内数据实时核算（否则视为仍在核算）。
    """
    if not venue_name:
        return {"ok": False, "reason": "场馆名称不能为空"}

    existing = _find_by_request_id(client_request_id)
    if existing is not None:
        return {"ok": True, "reused": True, "reason": "重复请求，返回已保存的对账包",
                "package_no": existing["package_no"],
                "round_no": len(existing.get("rounds", [])),
                "missing": existing.get("missing", []),
                "warning": existing.get("warning", ""),
                "package": _public_view(existing)}

    package = _find_package(package_no) if package_no else None
    if package_no and package is None:
        return {"ok": False, "reason": f"对账包 {package_no} 不存在"}

    created = False
    if package is None:
        package = _open_package_for(venue_name)

    if package is None:
        package_id = store.next_id(PACKAGE_MODULE)
        package = {
            "id": package_id,
            "package_no": f"QPKG-{_today()}-{package_id:04d}",
            "venue_name": venue_name,
            "status": STATUS_INCOMPLETE,
            "pending": True,
            "abnormal": False,
            "rounds": [],
            "client_request_ids": [],
            "superseded_areas": [],
            "created_at": _now(),
            "created_by": operator,
            "self_area_occupancy": 0.0,
        }
        store.rows(PACKAGE_MODULE).append(package)
        created = True

    if client_request_id and client_request_id not in package["client_request_ids"]:
        package["client_request_ids"].append(client_request_id)

    # 已完成的包不再改写，必须另开新包，保证历史签发依据不被回写。
    if package.get("status") == STATUS_COMPLETE:
        return {"ok": False,
                "reason": f"对账包 {package['package_no']} 已完成核对，不能再改写；请另建新包",
                "package": _public_view(package)}

    versions = source_versions(venue_name)

    # 未显式给面积时，按场馆实时采集；功率缺省表示「仍在核算」。
    area_snapshot = capture_area(venue_name, area) if area is not None else None
    if area_snapshot is None and (power is None or capture_power_live):
        # 允许先存面积：调用方只关心功率仍在核算。
        area_snapshot = capture_area(venue_name)

    power_snapshot = _normalize_power(power) if power is not None else None
    if power_snapshot is None and capture_power_live:
        power_snapshot = capture_power(venue_name)

    # 完全重复的一轮不再追加。
    last = _last_round(package)
    if last is not None:
        same_area = (area_snapshot or None) == last.get("area")
        same_power = (power_snapshot or None) == last.get("power")
        if same_area and same_power:
            return {"ok": True, "reused": True, "reason": "重复请求，返回已保存的对账包",
                    "package": _public_view(package)}

    round_no = len(package["rounds"]) + 1
    area_origin = round_no
    if area_snapshot is None and package.get("area"):
        # 只补功率时，面积沿用最近一次场内记录，并在新轮中重新封存。
        area_snapshot = copy.deepcopy(package["area"])
        area_origin = int(package.get("area_round") or round_no)

    round_data = _make_round(round_no, area_snapshot, power_snapshot,
                             versions, operator, reason)
    round_data["area_source_round"] = area_origin
    if area_snapshot and area_snapshot.get("correction"):
        round_data["area_correction"] = {
            "from_remaining": area_snapshot.get("corrected_from_remaining"),
            "to_remaining": area_snapshot.get("remaining"),
            "note": area_snapshot.get("correction_note", ""),
        }
    _apply_round(package, round_data)

    store.event_log.record(
        module=PACKAGE_MODULE,
        entry_id=package["id"],
        action="保存对账包",
        after=copy.deepcopy(package),
        extra={"booth_no": "", "package_no": package["package_no"],
               "venue_name": venue_name, "round_no": round_no,
               "missing": package.get("missing", [])},
    )

    return {
        "ok": True,
        "created": created,
        "reused": False,
        "package_no": package["package_no"],
        "round_no": round_no,
        "missing": package.get("missing", []),
        "warning": package.get("warning", ""),
        "package": _public_view(package),
    }


def complete_package(
    package_no: str,
    power: dict[str, Any] | None = None,
    area: dict[str, Any] | None = None,
    *,
    operator: str = "",
    client_request_id: str | None = None,
) -> dict[str, Any]:
    """补齐功率核验：在新一轮里同时重新封存面积与功率，确保㎡和kW同轮。"""
    package = _find_package(package_no)
    if package is None:
        return {"ok": False, "reason": f"对账包 {package_no} 不存在"}

    if client_request_id and client_request_id in package.get("client_request_ids", []):
        return {"ok": True, "reused": True, "reason": "重复请求，对账包已补齐",
                "package": _public_view(package)}

    if package.get("status") == STATUS_COMPLETE:
        return {"ok": False, "reason": f"对账包 {package_no} 已完成核对",
                "package": _public_view(package)}

    venue_name = str(package.get("venue_name", ""))
    if client_request_id:
        package.setdefault("client_request_ids", []).append(client_request_id)

    # 面积在补齐这一轮重新封存：优先显式传入，否则沿用包内最新一次场内面积。
    if area is not None:
        area_snapshot = capture_area(venue_name, area)
        area_source_round = len(package["rounds"]) + 1
    elif package.get("area"):
        area_snapshot = copy.deepcopy(package["area"])
        area_source_round = int(package.get("area_round") or len(package["rounds"]))
    else:
        area_snapshot = capture_area(venue_name)
        area_source_round = len(package["rounds"]) + 1

    if power is None:
        power_snapshot = capture_power(venue_name)
    else:
        power_snapshot = _normalize_power(power)

    round_no = len(package["rounds"]) + 1
    round_data = _make_round(round_no, area_snapshot, power_snapshot,
                             source_versions(venue_name), operator, "补齐功率核验")
    round_data["area_source_round"] = area_source_round
    _apply_round(package, round_data)
    package["completed_at"] = _now()
    package["completed_by"] = operator

    store.event_log.record(
        module=PACKAGE_MODULE,
        entry_id=package["id"],
        action="补齐并封存对账包",
        after=copy.deepcopy(package),
        extra={"package_no": package_no, "venue_name": venue_name,
               "round_no": round_no,
               "adopted_area_remaining": _num((package.get("adopted_area") or {}).get("remaining"))},
    )

    return {
        "ok": True,
        "package_no": package_no,
        "round_no": round_no,
        "adopted_round": package.get("adopted_round"),
        "adopted_area_remaining": _num((package.get("adopted_area") or {}).get("remaining")),
        "warning": package.get("warning", ""),
        "package": _public_view(package),
    }


def get_package(package_no: str) -> dict[str, Any] | None:
    package = _find_package(package_no)
    return _public_view(package) if package else None


def list_packages(venue_name: str | None = None,
                  status: str | None = None) -> list[dict[str, Any]]:
    packages = list(store.rows(PACKAGE_MODULE))
    if venue_name:
        packages = [p for p in packages if str(p.get("venue_name", "")) == venue_name]
    if status:
        packages = [p for p in packages if p.get("status") == status]
    packages.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return [_public_view(p) for p in packages]


def latest_package(venue_name: str) -> dict[str, Any] | None:
    packages = [p for p in store.rows(PACKAGE_MODULE)
                if str(p.get("venue_name", "")) == venue_name]
    if not packages:
        return None
    packages.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return _public_view(packages[0])


def readiness(package_no: str) -> dict[str, Any]:
    """只读核对结论：未完成时给出提示，不阻断查询。"""
    package = _find_package(package_no)
    if package is None:
        return {"ok": False, "reason": f"对账包 {package_no} 不存在"}
    missing = package.get("missing", [])
    ready = package.get("status") == STATUS_COMPLETE
    return {
        "ok": True,
        "package_no": package_no,
        "ready": ready,
        "status": package.get("status"),
        "missing": missing,
        "warning": "" if ready else
        f"核对未完成：缺少{'、'.join(missing)}，可继续查看明细，但不能办理新排位",
        "message": "可作为排位签发依据" if ready else
        f"核对未完成：缺少{'、'.join(missing)}",
        "package": _public_view(package),
    }


# ---------- 排位签发 ----------

def _find_placement_by_request_id(client_request_id: str | None) -> dict[str, Any] | None:
    if not client_request_id:
        return None
    for placement in store.rows(PLACEMENT_MODULE):
        if placement.get("client_request_id") == client_request_id:
            return placement
    return None


def issue_placement(
    package_no: str,
    booth_no: str,
    *,
    slot_no: str = "",
    operator: str = "",
    client_request_id: str | None = None,
) -> dict[str, Any]:
    """凭对账包办理排位；缺项的包只能看提示，不能签发。"""
    package = _find_package(package_no)
    if package is None:
        return {"ok": False, "reason": f"对账包 {package_no} 不存在", "package_no": package_no}

    existing = _find_placement_by_request_id(client_request_id)
    if existing is not None:
        return {"ok": True, "reused": True, "reason": "重复请求，返回已签发的排位",
                "placement": copy.deepcopy(existing),
                "package_no": existing.get("package_no")}

    if not booth_no:
        return {"ok": False, "reason": "缺少排位展位编号", "package_no": package_no}

    missing = package.get("missing", _missing_parts(package))
    if package.get("status") != STATUS_COMPLETE or missing:
        return {
            "ok": False,
            "package_no": package_no,
            "reason": f"对账包 {package_no} 核对未完成（缺少：{'、'.join(missing)}），不能办理新排位",
            "missing": missing,
            "status": package.get("status"),
            "warning": package.get("warning", ""),
        }

    area = package.get("adopted_area") or {}
    power = package.get("adopted_power") or {}
    if not area or not power:
        return {"ok": False, "package_no": package_no,
                "reason": "对账包缺少同轮的面积与功率封存结果，不能作为签发依据",
                "missing": _missing_parts(package)}

    # 包完成即代表两项均已核算；功率超载属于复核所见事实，写入排位但不阻断签发。

    placement = {
        "id": store.next_id(PLACEMENT_MODULE),
        "package_no": package_no,
        "venue_name": package.get("venue_name", ""),
        "booth_no": booth_no,
        "slot_no": slot_no,
        "operator": operator,
        "client_request_id": client_request_id,
        "status": "已签发",
        "pending": False,
        "abnormal": False,
        "adopted_round": package.get("adopted_round"),
        "adopted_area": copy.deepcopy(area),
        "adopted_power": copy.deepcopy(power),
        "adopted_area_remaining": _num(area.get("remaining")),
        "source_versions": copy.deepcopy(package.get("source_versions") or {}),
        "created_at": _now(),
        "self_area_occupancy": 0.0,
    }
    store.rows(PLACEMENT_MODULE).append(placement)

    store.event_log.record(
        module=PLACEMENT_MODULE,
        entry_id=placement["id"],
        action="凭对账包签发排位",
        after=copy.deepcopy(placement),
        extra={"booth_no": booth_no, "package_no": package_no,
               "venue_name": placement["venue_name"],
               "adopted_round": placement["adopted_round"],
               "adopted_area_remaining": placement["adopted_area_remaining"]},
    )

    return {
        "ok": True,
        "reason": f"排位已按对账包 {package_no} 第 {package.get('adopted_round')} 轮签发",
        "package_no": package_no,
        "placement": placement,
        "basis": {
            "adopted_round": package.get("adopted_round"),
            "area_detail": copy.deepcopy(area),
            "power_detail": copy.deepcopy(power),
            "source_versions": copy.deepcopy(package.get("source_versions") or {}),
            "note": "签发采用对账包封存轮次的面积，不再回读场馆后续更正",
        },
    }


def list_placements(package_no: str | None = None) -> list[dict[str, Any]]:
    placements = list(store.rows(PLACEMENT_MODULE))
    if package_no:
        placements = [p for p in placements if p.get("package_no") == package_no]
    return sorted(placements, key=lambda p: p.get("created_at", 0), reverse=True)
