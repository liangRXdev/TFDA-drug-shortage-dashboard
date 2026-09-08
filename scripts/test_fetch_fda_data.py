# -*- coding: utf-8 -*-
"""ETL fail-closed / schema 驗證測試（TG-01 / TG-02）。

無網路依賴：以 fake session 或 monkeypatch 取代 requests.get。
執行：uv run --with pytest --with requests pytest scripts/test_fetch_fda_data.py
"""
import os
import sys
import json
from datetime import datetime

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
import fetch_fda_data as etl  # noqa: E402


# ----------------------------------------------------------------------
# 測試輔助
# ----------------------------------------------------------------------
def row(**overrides):
    base = {
        "編號": "1",
        "公告更新時間": "2025/01/01",
        "中文品名": "DrugA",
        "許可證字號": "衛署藥製字第001號",
        "供應狀態": "短缺中",
    }
    base.update(overrides)
    return base


class FakeResponse:
    def __init__(self, payload, status=200, raise_exc=None):
        self._payload = payload
        self.status_code = status
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """依 URL 回傳預設回應；未設定的 URL 視為 404。"""
    def __init__(self, by_url):
        self.by_url = by_url
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        resp = self.by_url.get(url)
        if resp is None:
            return FakeResponse([], status=404)
        if isinstance(resp, Exception):
            raise resp
        return resp


def all_ok_session():
    return FakeSession({
        url: FakeResponse([row(編號=str(i))])
        for i, url in enumerate(etl.API_ENDPOINTS.values())
    })


# ======================================================================
# TG-02：schema / sentinel / 筆數
# ======================================================================
class TestValidateAndNormalize:
    def test_valid_list_passes(self):
        data = [row(), row(編號="2")]
        assert etl.validate_and_normalize("k", data) == data

    def test_non_list_raises(self):
        with pytest.raises(etl.DataFetchError):
            etl.validate_and_normalize("k", {"編號": "1"})

    def test_sentinel_normalized_to_empty(self):
        sentinel = [{"編號": "沒有資料", "公告更新時間": None,
                     "中文品名": None, "許可證字號": None, "供應狀態": None}]
        assert etl.is_sentinel(sentinel) is True
        assert etl.validate_and_normalize("54505_no_alternative", sentinel) == []

    def test_empty_list_without_sentinel_raises(self):
        # 空陣列但無哨兵 → 視為異常，不可被當成「零短缺」
        with pytest.raises(etl.DataFetchError):
            etl.validate_and_normalize("k", [])

    def test_wrong_field_type_raises(self):
        with pytest.raises(etl.DataFetchError):
            etl.validate_and_normalize("k", [row(供應狀態=123)])

    def test_null_fields_allowed(self):
        # 真實資料常見 null 欄位（如某些列 許可證字號 為 null）→ 不應被拒
        data = [row(許可證字號=None, 中文品名=None)]
        assert etl.validate_and_normalize("k", data) == data

    def test_non_dict_row_raises(self):
        with pytest.raises(etl.DataFetchError):
            etl.validate_and_normalize("k", ["not-a-dict"])


class TestCheckSanity:
    def test_all_empty_raises(self):
        datasets = {"a": [], "b": [], "c": []}
        with pytest.raises(etl.DataFetchError):
            etl.check_sanity(datasets)

    def test_non_empty_no_warning(self):
        datasets = {"a": [row()], "b": [], "c": []}
        assert etl.check_sanity(datasets) == []

    def test_drastic_drop_warns_but_not_fatal(self):
        datasets = {"a": [row()]}  # 1 筆
        previous = {"datasets": {"a": [row() for _ in range(100)]}}  # 前次 100 筆
        warnings = etl.check_sanity(datasets, previous)
        assert len(warnings) == 1
        assert "驟降" in warnings[0]

    def test_no_previous_no_warning(self):
        assert etl.check_sanity({"a": [row()]}, None) == []


# ======================================================================
# TG-01：fail-closed / 原檔保留
# ======================================================================
class TestFetchAllFailClosed:
    def test_single_endpoint_http_error_propagates(self):
        urls = list(etl.API_ENDPOINTS.values())
        session = FakeSession({
            urls[0]: FakeResponse([row()]),
            urls[1]: FakeResponse([], status=500),  # 第二個端點 500
            urls[2]: FakeResponse([row()]),
        })
        with pytest.raises(requests.HTTPError):
            etl.fetch_all(session=session)

    def test_connection_error_propagates(self):
        urls = list(etl.API_ENDPOINTS.values())
        session = FakeSession({urls[0]: requests.ConnectionError("boom")})
        with pytest.raises(requests.ConnectionError):
            etl.fetch_all(session=session)

    def test_json_decode_error_propagates(self):
        urls = list(etl.API_ENDPOINTS.values())
        session = FakeSession({urls[0]: FakeResponse(ValueError("bad json"))})
        with pytest.raises(ValueError):
            etl.fetch_all(session=session)

    def test_all_endpoints_fail(self):
        session = FakeSession({})  # 全部 → 404
        with pytest.raises(requests.HTTPError):
            etl.fetch_all(session=session)


class TestRunPreservesOriginalOnFailure:
    def _seed(self, tmp_path):
        out = tmp_path / "supply_status_latest.json"
        original = {"last_updated": "2000-01-01 00:00:00",
                    "datasets": {"keep": [row(編號="ORIGINAL")]}}
        out.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        return out, out.read_bytes()

    def test_fetch_failure_does_not_touch_output(self, tmp_path):
        out, original_bytes = self._seed(tmp_path)
        session = FakeSession({})  # 抓取全失敗
        with pytest.raises(requests.HTTPError):
            etl.run(output_path=str(out), session=session)
        assert out.read_bytes() == original_bytes  # 原檔完全未動

    def test_all_empty_sanity_failure_does_not_touch_output(self, tmp_path):
        out, original_bytes = self._seed(tmp_path)
        # 三端點皆回哨兵（正規化為空）→ check_sanity 應致命
        sentinel = [{"編號": "沒有資料", "公告更新時間": None,
                     "中文品名": None, "許可證字號": None, "供應狀態": None}]
        session = FakeSession({u: FakeResponse(sentinel) for u in etl.API_ENDPOINTS.values()})
        with pytest.raises(etl.DataFetchError):
            etl.run(output_path=str(out), session=session)
        assert out.read_bytes() == original_bytes

    def test_main_exits_nonzero_and_preserves_file(self, tmp_path, monkeypatch):
        out, original_bytes = self._seed(tmp_path)
        monkeypatch.setattr(etl, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(etl, "OUTPUT_FILENAME", "supply_status_latest.json")
        # 讓 fetch_all 直接失敗
        def boom(*a, **k):
            raise requests.ConnectionError("down")
        monkeypatch.setattr(etl, "fetch_all", boom)
        with pytest.raises(SystemExit) as ei:
            etl.main()
        assert ei.value.code == 1
        assert out.read_bytes() == original_bytes


class TestRunSuccessPath:
    def test_success_writes_atomically(self, tmp_path):
        out = tmp_path / "supply_status_latest.json"
        session = all_ok_session()
        payload = etl.run(output_path=str(out), session=session)
        assert out.exists()
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["datasets"] == payload["datasets"]
        # 三個資料集各 1 筆
        assert sum(len(v) for v in on_disk["datasets"].values()) == 3
        # 無殘留暫存檔
        assert [p for p in os.listdir(tmp_path) if p.endswith(".tmp")] == []

    def test_success_overwrites_previous(self, tmp_path):
        out = tmp_path / "supply_status_latest.json"
        out.write_text(json.dumps({"last_updated": "old", "datasets": {}}),
                       encoding="utf-8")
        etl.run(output_path=str(out), session=all_ok_session())
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["last_updated"] != "old"


# ======================================================================
# 增量 F：上游停更偵測（規格 .ai-review/plan-upstream-freeze.md）
#
# 每個 class 對應驗收條件，並刻意堵死 plan-verdict 區塊 3 指名的弱化實作
# （「永遠回零」「只讀第一個資料集」「有 log 就算 warning」…）。
# ======================================================================
FIXED_NOW = datetime(2026, 9, 4, 4, 10, 50, tzinfo=etl.TAIPEI_TZ)   # 2026-W36


def dated(d, **kw):
    return row(公告更新時間=d, **kw)


class TestParseUpstreamDate:
    """F2：有效日期須為真實曆日，不只是字面格式。"""

    def test_valid_date(self):
        assert etl.parse_upstream_date("2026/08/31") == "2026/08/31"

    def test_strips_whitespace(self):
        assert etl.parse_upstream_date("  2026/08/31  ") == "2026/08/31"

    @pytest.mark.parametrize("bad", [
        "2026/02/30",   # 格式對但非真實曆日
        "2026/13/01",   # 月份越界
        "2026-08-31",   # 分隔符不同
        "2026/8/31",    # 未補零
        "N/A", "", "   ", None, 20260831, [], {},
    ])
    def test_invalid_rejected(self, bad):
        assert etl.parse_upstream_date(bad) is None


class TestExtractUpstreamMaxDate:
    """F1：跨資料集取最大值，且不受列序／資料集序影響。"""

    def test_each_dataset_can_be_sole_max_source(self):
        for winner in ("a", "b", "c"):
            datasets = {k: [dated("2020/01/01"), dated("2021/06/30")]
                        for k in ("a", "b", "c")}
            datasets[winner] = datasets[winner] + [dated("2026/08/31")]
            got, invalid = etl.extract_upstream_max_date(datasets, now=FIXED_NOW)
            assert got == "2026/08/31", winner
            assert invalid is False

    def test_order_independence(self):
        """堵死「只讀第一個非空資料集／最後一列」的弱化實作。"""
        dates = ["2024/12/31", "2026/08/31", "2019/01/01", "2025/02/28"]
        base = {"a": [dated(d) for d in dates], "b": [], "c": [dated("2023/07/04")]}
        expected, _ = etl.extract_upstream_max_date(base, now=FIXED_NOW)
        assert expected == "2026/08/31"
        rev_rows = {"a": list(reversed(base["a"])), "b": [], "c": base["c"]}
        assert etl.extract_upstream_max_date(rev_rows, now=FIXED_NOW)[0] == expected
        rev_sets = {k: base[k] for k in reversed(list(base))}
        assert etl.extract_upstream_max_date(rev_sets, now=FIXED_NOW)[0] == expected

    def test_cross_month_and_year(self):
        datasets = {"a": [dated("2025/12/31"), dated("2026/01/01")]}
        assert etl.extract_upstream_max_date(datasets, now=FIXED_NOW)[0] == "2026/01/01"

    def test_invalid_never_becomes_max(self):
        datasets = {"a": [dated("2026/08/31"), dated("9999/99/99")]}
        got, invalid = etl.extract_upstream_max_date(datasets, now=FIXED_NOW)
        assert got == "2026/08/31"
        assert invalid is True

    def test_all_empty_returns_none(self):
        got, invalid = etl.extract_upstream_max_date({"a": [], "b": []}, now=FIXED_NOW)
        assert got is None and invalid is False

    def test_rows_are_never_dropped(self):
        """F2：容錯只略過日期候選，不得刪除公告列。"""
        datasets = {"a": [dated("N/A"), dated("2026/08/31"), dated(None)]}
        etl.extract_upstream_max_date(datasets, now=FIXED_NOW)
        assert len(datasets["a"]) == 3

    def test_newest_row_unparseable_flags_invalid(self):
        """僅最新列格式漂移 → 最大日期假性停住，必須標記可信度受損。"""
        datasets = {"a": [dated("2026/07/31"), dated("2026-09-06")]}
        got, invalid = etl.extract_upstream_max_date(datasets, now=FIXED_NOW)
        assert got == "2026/07/31"
        assert invalid is True


class TestObservationPeriod:
    def test_iso_week_format(self):
        assert etl.observation_period(FIXED_NOW) == "2026-W36"

    def test_same_week_different_days_same_period(self):
        d1 = datetime(2026, 8, 31, 1, 0, tzinfo=etl.TAIPEI_TZ)
        d2 = datetime(2026, 9, 6, 23, 0, tzinfo=etl.TAIPEI_TZ)
        assert etl.observation_period(d1) == etl.observation_period(d2)


class TestComputeFreezeState:
    """F4／F5／F6：狀態轉移。"""

    def prev(self, date_, runs, period="2026-W35"):
        return {"upstream_max_date": date_, "frozen_runs": runs,
                "last_observed_period": period, "datasets": {}}

    def test_advance_resets_to_zero(self):
        runs, warns = etl.compute_freeze_state(
            "2026/09/01", False, "2026-W36", self.prev("2026/08/24", 3))
        assert runs == 0 and warns == []

    def test_advance_updates_baseline_not_just_zero(self):
        """F4：堵死「永遠回零」——歸零後基準須確實改為新日期。"""
        first = etl.compute_freeze_state(
            "2026/09/01", False, "2026-W36", self.prev("2026/08/24", 3))[0]
        assert first == 0
        published = {"upstream_max_date": "2026/09/01", "frozen_runs": first,
                     "last_observed_period": "2026-W36"}
        assert etl.compute_freeze_state(
            "2026/09/01", False, "2026-W37", published)[0] == 1

    def test_equal_increments_across_periods(self):
        """F5：三個不同觀測區間逐次承接已發布結果 → 1, 2, 3。"""
        state = {"upstream_max_date": "2026/08/31", "frozen_runs": 0,
                 "last_observed_period": "2026-W36"}
        got = []
        for period in ("2026-W37", "2026-W38", "2026-W39"):
            runs, _ = etl.compute_freeze_state("2026/08/31", False, period, state)
            got.append(runs)
            state = {"upstream_max_date": "2026/08/31", "frozen_runs": runs,
                     "last_observed_period": period}
        assert got == [1, 2, 3]

    def test_same_period_reentry_does_not_accumulate(self):
        """F5：同一週重跑（手動 dispatch／retry）不得累加。"""
        state = {"upstream_max_date": "2026/08/31", "frozen_runs": 2,
                 "last_observed_period": "2026-W37"}
        for _ in range(5):
            runs, _ = etl.compute_freeze_state("2026/08/31", False, "2026-W37", state)
            assert runs == 2

    def test_regression_resets_and_warns_with_both_dates(self):
        """F6：堵死「任一 logger 有輸出就算 warning」。"""
        runs, warns = etl.compute_freeze_state(
            "2026/07/01", False, "2026-W36", self.prev("2026/08/31", 2))
        assert runs == 0
        assert len(warns) == 1
        assert "2026/08/31" in warns[0] and "2026/07/01" in warns[0]

    def test_regression_new_baseline_then_increments(self):
        published = {"upstream_max_date": "2026/07/01", "frozen_runs": 0,
                     "last_observed_period": "2026-W36"}
        assert etl.compute_freeze_state(
            "2026/07/01", False, "2026-W37", published)[0] == 1

    def test_none_is_not_equal_freezes_count(self):
        """F3：None 表無可比較基準，絕不可當作相等而累加。"""
        assert etl.compute_freeze_state(
            None, False, "2026-W37", self.prev("2026/08/31", 2))[0] == 2

    def test_none_to_none_freezes_count(self):
        assert etl.compute_freeze_state(
            None, False, "2026-W37", self.prev(None, 0))[0] == 0

    def test_none_to_valid_rebuilds_baseline(self):
        assert etl.compute_freeze_state(
            "2026/09/01", False, "2026-W37", self.prev(None, 0))[0] == 0

    def test_invalid_date_present_suspends_accumulation(self):
        """B1-3：格式漂移時暫停累計而非誤報凍結。"""
        assert etl.compute_freeze_state(
            "2026/08/31", True, "2026-W37", self.prev("2026/08/31", 2))[0] == 2


class TestPreviousStateContract:
    """F7：前版狀態異常的處置契約（§4.4）。"""

    @pytest.mark.parametrize("previous", [
        None,
        {"last_updated": "x", "datasets": {}},
        {"frozen_runs": 3},
        {"upstream_max_date": "2026/08/31"},
        {"upstream_max_date": "2026/08/31", "frozen_runs": -1},
        {"upstream_max_date": "2026/08/31", "frozen_runs": 2.5},
        {"upstream_max_date": "2026/08/31", "frozen_runs": "3"},
        {"upstream_max_date": "2026/08/31", "frozen_runs": True},
        {"upstream_max_date": "2026/02/30", "frozen_runs": 2},
        {"upstream_max_date": None, "frozen_runs": 3},
        {"upstream_max_date": "2026/08/31", "frozen_runs": 2,
         "last_observed_period": 36},
        "not-a-dict",
    ])
    def test_invalid_or_absent_state_rebuilds_baseline(self, previous):
        runs, _ = etl.compute_freeze_state("2026/08/31", False, "2026-W37", previous)
        assert runs == 0

    def test_unreadable_previous_file_fails_closed(self, tmp_path):
        """前檔存在但無法解析 → 不得當成首次執行。"""
        out = tmp_path / "supply_status_latest.json"
        out.write_text("{ not json", encoding="utf-8")
        with pytest.raises(etl.DataFetchError):
            etl.load_previous(str(out))

    def test_missing_previous_file_is_not_an_error(self, tmp_path):
        assert etl.load_previous(str(tmp_path / "nope.json")) is None


class TestBuildPayloadSemantics:
    """F8：檢查時間隨執行前進，上游日期不隨之改變。"""

    def test_check_time_advances_while_upstream_date_holds(self):
        t1 = datetime(2026, 9, 4, 4, 0, 0, tzinfo=etl.TAIPEI_TZ)
        t2 = datetime(2026, 9, 11, 4, 0, 0, tzinfo=etl.TAIPEI_TZ)
        datasets = {"a": [dated("2026/08/31")]}
        p1 = etl.build_payload(datasets, now=t1, upstream_max_date="2026/08/31",
                               frozen_runs=0, last_observed_period="2026-W36")
        p2 = etl.build_payload(datasets, now=t2, upstream_max_date="2026/08/31",
                               frozen_runs=1, last_observed_period="2026-W37")
        assert p1["last_updated"] != p2["last_updated"]
        assert p1["upstream_max_date"] == p2["upstream_max_date"]
        assert (p1["frozen_runs"], p2["frozen_runs"]) == (0, 1)
        assert p1["datasets"] == p2["datasets"]

    def test_null_schema_is_valid(self):
        p = etl.build_payload({"a": []}, now=FIXED_NOW, upstream_max_date=None)
        assert p["upstream_max_date"] is None
        assert p["frozen_runs"] == 0
        assert p["last_observed_period"] == "2026-W36"


class TestRunIntegration:
    """F3／F9／F15a：端到端序列與 fail-closed 未退化。"""

    def _session(self, dates):
        urls = list(etl.API_ENDPOINTS.values())
        return FakeSession({
            u: FakeResponse([dated(d, 編號=str(i))])
            for i, (u, d) in enumerate(zip(urls, dates))
        })

    def test_end_to_end_writes_detection_fields(self, tmp_path):
        out = tmp_path / "p.json"
        etl.run(output_path=str(out),
                session=self._session(["2026/08/31", "2026/08/01", "2026/07/04"]),
                now=FIXED_NOW)
        got = json.loads(out.read_text(encoding="utf-8"))
        assert got["upstream_max_date"] == "2026/08/31"
        assert got["frozen_runs"] == 0
        assert got["last_observed_period"] == "2026-W36"

    def test_sequence_across_weeks_accumulates(self, tmp_path):
        """F15a：以固定觀測序列驗狀態機（可控、可重現）。"""
        out = tmp_path / "p.json"
        weeks = [datetime(2026, 9, 4 + 7 * i, 4, 0, tzinfo=etl.TAIPEI_TZ)
                 for i in range(4)]
        got = []
        for now in weeks:
            payload = etl.run(output_path=str(out),
                              session=self._session(["2026/08/31", "2026/08/01",
                                                     "2026/07/04"]),
                              now=now)
            got.append(payload["frozen_runs"])
        assert got == [0, 1, 2, 3]

    def test_same_week_reruns_do_not_accumulate(self, tmp_path):
        """F15a 反例：短時間重跑不得推高計數。"""
        out = tmp_path / "p.json"
        payload = None
        for _ in range(4):
            payload = etl.run(output_path=str(out),
                              session=self._session(["2026/08/31", "2026/08/01",
                                                     "2026/07/04"]),
                              now=FIXED_NOW)
        assert payload["frozen_runs"] == 0

    def test_all_sentinel_still_fails_closed(self, tmp_path):
        """既有不變量：三端點皆空仍拒絕發布（CR-01），不因本增量放寬。"""
        out = tmp_path / "p.json"
        original = {"last_updated": "2000-01-01 00:00:00", "datasets": {"keep": [row()]}}
        out.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        before = out.read_bytes()
        sentinel = [{"編號": "沒有資料", "公告更新時間": None, "中文品名": None,
                     "許可證字號": None, "供應狀態": None}]
        session = FakeSession({u: FakeResponse(sentinel)
                               for u in etl.API_ENDPOINTS.values()})
        with pytest.raises(etl.DataFetchError):
            etl.run(output_path=str(out), session=session, now=FIXED_NOW)
        assert out.read_bytes() == before

    def test_no_valid_dates_publishes_null_and_no_accumulation(self, tmp_path):
        """F3 可達路徑：資料非空但日期全無效 → null，且不累計。"""
        out = tmp_path / "p.json"
        payload = etl.run(output_path=str(out),
                          session=self._session(["N/A", "N/A", "N/A"]),
                          now=FIXED_NOW)
        assert payload["upstream_max_date"] is None
        assert payload["frozen_runs"] == 0

    def test_state_computation_failure_preserves_file(self, tmp_path, monkeypatch):
        """F9：狀態計算失敗也須 fail-closed，正式檔逐位元不變。"""
        out = tmp_path / "p.json"
        original = {"last_updated": "2000-01-01 00:00:00", "frozen_runs": 7,
                    "upstream_max_date": "2026/08/31", "datasets": {"keep": [row()]}}
        out.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        before = out.read_bytes()

        def boom(*a, **k):
            raise RuntimeError("state calc exploded")
        monkeypatch.setattr(etl, "compute_freeze_state", boom)
        with pytest.raises(RuntimeError):
            etl.run(output_path=str(out),
                    session=self._session(["2026/08/31", "2026/08/01", "2026/07/04"]),
                    now=FIXED_NOW)
        assert out.read_bytes() == before

    def test_atomic_write_failure_preserves_file(self, tmp_path, monkeypatch):
        out = tmp_path / "p.json"
        original = {"last_updated": "2000-01-01 00:00:00", "datasets": {"keep": [row()]}}
        out.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        before = out.read_bytes()

        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(etl, "write_atomic", boom)
        with pytest.raises(OSError):
            etl.run(output_path=str(out),
                    session=self._session(["2026/08/31", "2026/08/01", "2026/07/04"]),
                    now=FIXED_NOW)
        assert out.read_bytes() == before
