"""TFDA 西藥供應 ETL（fail-closed）。

設計原則（對應 .ai-review/verdict.md）：
- CR-01：任一必要端點連線／HTTP／JSON／驗證失敗即 fail-closed，以非零狀態結束，
  「不覆寫」既有正式 JSON；全部成功後才以 os.replace 原子替換。
  另有 sanity check：所有資料集皆空時拒絕發布近乎空白的儀表板。
- CR-02：對 API 回傳做結構驗證（須為 list、欄位型別檢查），並將 TFDA 的
  「沒有資料」sentinel 明確辨識為「官方回覆空集」，與「抓取失敗」區分。

所有純邏輯皆抽為可 import 的函式，供 pytest 在無網路下 mock 測試。
"""
import os
import sys
import json
import tempfile
from datetime import datetime

import requests

API_ENDPOINTS = {
    "54504_with_alternative": "https://data.fda.gov.tw/data/opendata/export/104/json",
    "54505_no_alternative": "https://data.fda.gov.tw/data/opendata/export/105/json",
    "54506_resolved": "https://data.fda.gov.tw/data/opendata/export/106/json",
}

REQUIRED_FIELDS = ["編號", "公告更新時間", "中文品名", "許可證字號", "供應狀態"]
SENTINEL_ID = "沒有資料"          # TFDA 對「查無資料」回傳的哨兵列標記
REQUEST_TIMEOUT = 30              # 秒；保留明確 timeout
DRASTIC_DROP_RATIO = 0.5         # 相對前次筆數驟降告警門檻（非致命）

OUTPUT_DIR = "public/data"
OUTPUT_FILENAME = "supply_status_latest.json"


class DataFetchError(Exception):
    """ETL 過程中任何足以中止發布的錯誤。"""


def fetch_raw(url, timeout=REQUEST_TIMEOUT, session=None):
    """抓取單一端點並回傳已解析 JSON。

    失敗（連線／HTTP 4xx-5xx／JSON decode）會 raise，交由上層 fail-closed，
    刻意不吞例外、不回傳空集（此為 CR-01 的根因）。TLS 驗證維持預設開啟。
    """
    getter = (session or requests).get
    response = getter(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def is_sentinel(rows):
    """判斷是否為 TFDA『沒有資料』哨兵回應（官方回覆空集，屬合法狀態）。"""
    return (
        isinstance(rows, list)
        and len(rows) == 1
        and isinstance(rows[0], dict)
        and rows[0].get("編號") == SENTINEL_ID
    )


def validate_and_normalize(key, raw):
    """驗證單一資料集結構並正規化。

    - 非 list → 失敗
    - 『沒有資料』哨兵 → 正規化為 []（合法空集）
    - 空 list 但無哨兵 → 失敗（視為異常，避免把錯誤當成「零短缺」）
    - 每列須為 dict，且出現的必要欄位型別須為 str 或 None
    """
    if not isinstance(raw, list):
        raise DataFetchError(f"{key}: 回傳非陣列（type={type(raw).__name__}）")

    if is_sentinel(raw):
        return []

    if len(raw) == 0:
        raise DataFetchError(f"{key}: 回傳空陣列且無「{SENTINEL_ID}」標記，判定為異常回應")

    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise DataFetchError(f"{key}[{idx}]: 資料列非物件（type={type(row).__name__}）")
        for field in REQUIRED_FIELDS:
            value = row.get(field)
            if value is not None and not isinstance(value, str):
                raise DataFetchError(
                    f"{key}[{idx}].{field}: 型別非字串（{type(value).__name__}）"
                )
    return raw


def fetch_all(endpoints=None, session=None):
    """抓取並驗證所有端點；任一端點失敗即 raise（fail-closed）。"""
    endpoints = endpoints or API_ENDPOINTS
    datasets = {}
    for key, url in endpoints.items():
        print(f"📥 抓取 {key} ...")
        raw = fetch_raw(url, session=session)
        datasets[key] = validate_and_normalize(key, raw)
        print(f"✅ {key}: {len(datasets[key])} 筆（驗證通過）")
    return datasets


def load_previous(path):
    """讀取前一版 JSON；不存在或損毀時回傳 None（不視為錯誤）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def check_sanity(datasets, previous=None):
    """發布前健全性檢查。

    - 致命：所有資料集皆空 → raise（拒絕發布近乎空白的儀表板）
    - 非致命：相對前次筆數驟降 → 回傳警示字串清單（僅記錄，不阻擋）
    """
    total = sum(len(v) for v in datasets.values())
    if total == 0:
        raise DataFetchError("所有資料集皆為空，拒絕發布近乎空白的儀表板")

    warnings = []
    prev_datasets = (previous or {}).get("datasets")
    if isinstance(prev_datasets, dict):
        for key, rows in datasets.items():
            prev = prev_datasets.get(key)
            if isinstance(prev, list) and len(prev) > 0 and len(rows) < len(prev) * DRASTIC_DROP_RATIO:
                warnings.append(f"{key}: 筆數由 {len(prev)} 驟降至 {len(rows)}")
    return warnings


def build_payload(datasets, now=None):
    now = now or datetime.now()
    return {
        "last_updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "datasets": datasets,
    }


def write_atomic(path, payload):
    """先寫暫存檔再 os.replace 原子替換；失敗時清除暫存並保留原檔。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)  # 同目錄內 rename → 原子操作
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def run(output_path=None, endpoints=None, session=None):
    """ETL 主流程；成功回傳 payload，任一步失敗會 raise。"""
    output_path = output_path or os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
    datasets = fetch_all(endpoints=endpoints, session=session)
    warnings = check_sanity(datasets, load_previous(output_path))
    for w in warnings:
        print(f"⚠️ 警示：{w}")
    payload = build_payload(datasets)
    write_atomic(output_path, payload)
    return payload


def main():
    print(f"🚀 TFDA ETL 開始（{datetime.now().isoformat()}）")
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
    try:
        payload = run(output_path=output_path)
    except Exception as exc:  # noqa: BLE001 — 頂層 fail-closed 攔截
        print(
            f"❌ ETL 失敗（fail-closed，未覆寫 {output_path}）：{exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    total = sum(len(v) for v in payload["datasets"].values())
    print(f"🎉 已原子寫入 {output_path}（共 {total} 筆）")


if __name__ == "__main__":
    main()
