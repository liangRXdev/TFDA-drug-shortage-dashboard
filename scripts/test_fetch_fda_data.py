# -*- coding: utf-8 -*-
"""ETL fail-closed / schema 驗證測試（TG-01 / TG-02）。

無網路依賴：以 fake session 或 monkeypatch 取代 requests.get。
執行：uv run --with pytest --with requests pytest scripts/test_fetch_fda_data.py
"""
import os
import sys
import json

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
