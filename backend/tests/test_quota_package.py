"""配额对账包 - 保存、回查、跨轮采用面积与排位签发测试。

覆盖：
1. 只存面积、功率仍在核算时，包为「核对未完成」，可查不可签发
2. 对账包不登记展位、不增加面积占用
3. 保存响应中断后凭 client_request_id 重试拿回同一包号
4. 刷新包号后办排位仍被缺项拦截
5. 补齐功率时在新一轮重新封存面积，㎡ 与 kW 同轮
6. 实际采用补齐轮的更正面积（12㎡），而非最早写入的 28㎡
7. 主管凭包号可回查两项明细与现场版本
"""
import sys
import unittest

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import quota_package as q
from app.store import store

VENUE = "A馆主展厅"
POWER = {
    "booths": [
        {"booth_no": "BOOT-A01", "ok": True, "design_load": 80,
         "total_circuit_power": 75, "circuits": [{"circuit_id": "ELEC-A01-1", "power": 40}]},
        {"booth_no": "BOOT-A02", "ok": False, "design_load": 50,
         "total_circuit_power": 70, "circuits": [{"circuit_id": "ELEC-A02-1", "power": 35}]},
    ]
}


class QuotaPackageScenario(unittest.TestCase):
    def setUp(self):
        # 每个用例使用独立场馆名，避免包之间互相复用。
        self.venue = f"{VENUE}-{self._testMethodName}"
        self._add_venue(self.venue)
        self._add_booths(self.venue)

    def _add_venue(self, venue_name):
        store.rows("venue").append({
            "id": store.next_id("venue"), "status": "已确认", "pending": False,
            "abnormal": False, "场馆名称": venue_name, "可用面积": "2000",
            "层高限制": "12米", "地面承重": "5吨/㎡",
            "登记编号": f"V-{self._testMethodName}", "负责人": "测试",
            "生效版本": "v1.0", "备注说明": "",
        })

    def _add_booths(self, venue_name):
        rows = store.rows("booth")
        for suffix, area in (("01", 600), ("02", 400)):
            rows.append({
                "id": store.next_id("booth"), "status": "已确认", "pending": False,
                "abnormal": False, "展位编号": f"{venue_name}-{suffix}",
                "面积尺寸": str(area), "开口方向": "东", "所属区域": venue_name,
                "登记编号": f"T-{self._testMethodName}-{suffix}", "负责人": "测试",
                "生效版本": "v1.0", "备注说明": "",
            })
        store.rebuild_indices()

    def test_incomplete_package_blocks_placement(self):
        saved = q.save_package(self.venue, area={"remaining": 28}, power=None,
                               operator="签发员", client_request_id="save-1")
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["missing"], [q.PART_POWER])
        self.assertEqual(saved["package"]["status"], q.STATUS_INCOMPLETE)

        result = q.issue_placement(saved["package_no"], f"{self.venue}-01")
        self.assertFalse(result["ok"])
        self.assertIn("核对未完成", result["reason"])
        self.assertIn(q.PART_POWER, result["missing"])

    def test_package_does_not_add_area_occupancy(self):
        before = len(store.rows("booth"))
        saved = q.save_package(self.venue, area={"remaining": 28}, power=None)
        self.assertEqual(len(store.rows("booth")), before, "保存对账包不应登记展位")
        self.assertEqual(saved["package"]["self_area_occupancy"], 0.0)

    def test_retry_after_interrupted_response_returns_same_package(self):
        first = q.save_package(self.venue, area={"remaining": 28}, power=None,
                               operator="签发员", client_request_id="req-断线")
        retry = q.save_package(self.venue, area={"remaining": 28}, power=None,
                               operator="签发员", client_request_id="req-断线")
        self.assertTrue(retry["reused"])
        self.assertEqual(retry["package_no"], first["package_no"])
        # 刷新包号也能拿到同一个包
        latest = q.latest_package(self.venue)
        self.assertEqual(latest["package_no"], first["package_no"])

    def test_completion_reseals_area_and_adopts_corrected_remaining(self):
        saved = q.save_package(self.venue, area={"remaining": 28}, power=None)
        pno = saved["package_no"]

        completed = q.complete_package(pno, power=POWER, area={"remaining": 12,
                                                               "note": "场馆更正余量"},
                                       operator="签发员")
        self.assertTrue(completed["ok"])
        self.assertEqual(completed["adopted_area_remaining"], 12.0)

        view = q.get_package(pno)
        self.assertEqual(view["status"], q.STATUS_COMPLETE)
        # 面积与功率属于同一轮
        self.assertEqual(view["area_round"], view["power_round"])
        self.assertEqual(view["area_round"], completed["adopted_round"])
        # 旧的 28㎡ 被明确记为已被取代
        superseded = [s["remaining"] for s in view["superseded_areas"]]
        self.assertIn(28.0, superseded)

        booth_count = len(store.rows("booth"))
        placement = q.issue_placement(pno, f"{self.venue}-01", operator="签发员")
        self.assertTrue(placement["ok"], placement.get("reason"))
        self.assertEqual(placement["placement"]["adopted_area_remaining"], 12.0)
        self.assertEqual(placement["placement"]["adopted_round"], view["adopted_round"])
        # 签发排位同样只落记录，不新增展位面积
        self.assertEqual(len(store.rows("booth")), booth_count)
        self.assertEqual(placement["placement"]["self_area_occupancy"], 0.0)

    def test_lookup_returns_both_details_and_source_versions(self):
        saved = q.save_package(self.venue, area={"remaining": 28}, power=None)
        pno = saved["package_no"]
        q.complete_package(pno, power=POWER, area={"remaining": 12})

        view = q.get_package(pno)
        self.assertIsNotNone(view["area_detail"])
        self.assertEqual(view["area_detail"]["remaining"], 12.0)
        self.assertIsNotNone(view["power_detail"])
        self.assertEqual(len(view["power_detail"]["booths"]), 2)
        self.assertIn("venue", view["source_versions"])
        self.assertIn("booths", view["source_versions"])
        self.assertEqual(view["source_versions"]["venue"]["name"], self.venue)

    def test_completed_package_cannot_be_rewritten(self):
        saved = q.save_package(self.venue, area={"remaining": 28}, power=None)
        q.complete_package(saved["package_no"], power=POWER, area={"remaining": 12})
        result = q.complete_package(saved["package_no"], power=POWER)
        self.assertFalse(result["ok"])
        self.assertIn("已完成", result["reason"])

    def test_readiness_allows_lookup_but_warns(self):
        saved = q.save_package(self.venue, area={"remaining": 28}, power=None)
        readiness = q.readiness(saved["package_no"])
        self.assertTrue(readiness["ok"], "缺项查询本身不应失败")
        self.assertFalse(readiness["ready"])
        self.assertIn(q.PART_POWER, readiness["warning"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
