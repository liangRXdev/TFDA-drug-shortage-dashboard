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
import re
import sys
import json
import tempfile
from datetime import datetime, date, timezone, timedelta

import requests

# CR-11：GitHub runner 為 UTC，改以台灣時間（UTC+8）產生 last_updated，
# 避免台灣使用者看到少 8 小時的更新時間。
TAIPEI_TZ = timezone(timedelta(hours=8))

API_ENDPOINTS = {
    "54504_with_alternative": "https://data.fda.gov.tw/data/opendata/export/104/json",
    "54505_no_alternative": "https://data.fda.gov.tw/data/opendata/export/105/json",
    "54506_resolved": "https://data.fda.gov.tw/data/opendata/export/106/json",
}

REQUIRED_FIELDS = ["編號", "公告更新時間", "中文品名", "許可證字號", "供應狀態"]
SENTINEL_ID = "沒有資料"          # TFDA 對「查無資料」回傳的哨兵列標記
REQUEST_TIMEOUT = 30              # 秒；保留明確 timeout
DRASTIC_DROP_RATIO = 0.5         # 相對前次筆數驟降告警門檻（非致命）

# 上游停更偵測（增量 F，規格見 .ai-review/plan-upstream-freeze.md）
DATE_FIELD = "公告更新時間"
DATE_PATTERN = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")

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
    """讀取前一版 JSON。

    - 檔案不存在 → 回傳 None（首次執行，合法）
    - 檔案存在但無法讀取／解析 → raise（F7）。**不得**默認為首次執行：
      那會把損壞狀態悄悄轉成「重新建立基準」，使凍結計數無聲歸零。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise DataFetchError(f"前一版 {path} 存在但無法讀取／解析：{exc}") from exc


# ----------------------------------------------------------------------
# 上游停更偵測（增量 F）
#
# 判準是「上游最大公告日期有沒有前進」，不是「距今幾天」。
# 這**不是**與公告疏密無關——固定週排程下「連續 N 次未前進」等同
# 「約 N 週無新公告」；採用它的理由是可觀測性：計數在 ETL 端結算並寫入
# payload，是已發生觀測的事實，前端只呈現、不再以 Date.now() 重新判斷。
# 因此結論只能是「疑似訊號」：同日修訂、舊公告修正都不會改變最大日期。
# ----------------------------------------------------------------------
def parse_upstream_date(value):
    """把單一 `公告更新時間` 正規化為 `YYYY/MM/DD`；無效回 None。

    有效 = 字串、strip 後符合 YYYY/MM/DD、且為真實曆日。
    `2026/02/30`、`2026/13/01` 格式對但非真實日期，一律視為無效（F2）。
    """
    if not isinstance(value, str):
        return None
    m = DATE_PATTERN.match(value.strip())
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    try:
        date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}/{month:02d}/{day:02d}"


def extract_upstream_max_date(datasets, now=None):
    """回傳 `(最大有效日期或 None, 是否存在無效日期)`。

    無效日期**只**影響「能否成為最大日期候選」，不刪除任何公告列、
    也不繞過既有結構驗證——CR-01／CR-02 的失敗仍一律 fail-closed。

    第二個回傳值為可信度旗標：本次若有任何無效日期，最大日期可能
    「假性停住」（例如僅最新那列格式漂移、較舊列仍可解析），
    此時不得累積凍結證據（見 compute_freeze_state）。
    """
    now = now or datetime.now(TAIPEI_TZ)
    today = now.strftime("%Y/%m/%d")
    max_date = None
    has_invalid = False
    for rows in datasets.values():
        for row in rows:
            raw = row.get(DATE_FIELD) if isinstance(row, dict) else None
            parsed = parse_upstream_date(raw)
            if parsed is None:
                has_invalid = True
                continue
            if parsed > today:
                # 未來日期仍視為有效（不阻斷），但值得記錄
                print(f"⚠️ 警示：公告日期 {parsed} 晚於今日 {today}")
            if max_date is None or parsed > max_date:
                max_date = parsed
    return max_date, has_invalid


def observation_period(now=None):
    """本次執行所屬的觀測區間（台灣時間 ISO 週，如 `2026-W36`）。

    計數單位是觀測區間而非執行次數：同一週內重跑（手動 dispatch、retry）
    不重複累加，否則一天內跑 4 次即可觸發告警（F5）。
    """
    now = now or datetime.now(TAIPEI_TZ)
    iso = now.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def _valid_previous_state(previous):
    """從前一版 payload 取出**合法**的偵測狀態，否則回 None（歸零重建）。

    無效狀態一律重建基準，不做寬鬆解讀——那會把損壞資料轉成有效告警。
    `bool` 是 `int` 的子類，須明確排除。
    """
    if not isinstance(previous, dict):
        return None
    runs = previous.get("frozen_runs")
    if isinstance(runs, bool) or not isinstance(runs, int) or runs < 0:
        return None
    prev_date = previous.get("upstream_max_date")
    if prev_date is not None and parse_upstream_date(prev_date) is None:
        return None
    if prev_date is None and runs > 0:
        return None  # 有計數卻無日期基準 → 自相矛盾
    period = previous.get("last_observed_period")
    if period is not None and not isinstance(period, str):
        return None
    return {"frozen_runs": runs, "upstream_max_date": prev_date,
            "last_observed_period": period}


def compute_freeze_state(current_date, has_invalid, period, previous=None):
    """依 §4.3 狀態轉移表算出 `(frozen_runs, warnings)`。

    `None` 表示「無可比較基準」，**絕不可**當作「與前值相等」——
    把查不到日期誤判成上游凍結，正是本專案最不能犯的誤報方向。
    """
    warnings = []
    state = _valid_previous_state(previous)
    if state is None:
        return 0, warnings  # 首次、舊 schema、或狀態無效 → 建立基準

    prev_runs = state["frozen_runs"]
    prev_date = state["upstream_max_date"]

    if has_invalid:
        # 可信度受損：暫停累計而非誤報（漏報側，符合風險權重）
        return prev_runs, warnings
    if current_date is None or prev_date is None:
        return prev_runs, warnings  # 不可判定 → 凍結不動
    if current_date > prev_date:
        return 0, warnings
    if current_date < prev_date:
        warnings.append(
            f"上游最大公告日期倒退：{prev_date} → {current_date}（撤回公告？），重建基準"
        )
        return 0, warnings
    if period is not None and period == state["last_observed_period"]:
        return prev_runs, warnings  # 同一觀測區間重入 → 不重複累加
    return prev_runs + 1, warnings


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


def build_payload(datasets, now=None, upstream_max_date=None,
                  frozen_runs=0, last_observed_period=None):
    """組裝正式 payload。

    `last_updated` 語意為「ETL 最後成功**檢查**時間」——每次成功執行都會前進，
    與上游內容是否改變無關。判斷上游是否前進請用 `upstream_max_date`／
    `frozen_runs`，兩者語意不可混用（這正是本增量的起因）。
    """
    now = now or datetime.now(TAIPEI_TZ)
    return {
        "last_updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "upstream_max_date": upstream_max_date,
        "frozen_runs": frozen_runs,
        "last_observed_period": last_observed_period or observation_period(now),
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


def run(output_path=None, endpoints=None, session=None, now=None):
    """ETL 主流程；成功回傳 payload，任一步失敗會 raise。

    `now` 可注入固定時刻，讓觀測區間與檢查時間在測試中可控（F5／F8）。
    """
    output_path = output_path or os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
    now = now or datetime.now(TAIPEI_TZ)
    datasets = fetch_all(endpoints=endpoints, session=session)
    previous = load_previous(output_path)
    warnings = check_sanity(datasets, previous)

    upstream_max_date, has_invalid = extract_upstream_max_date(datasets, now=now)
    period = observation_period(now)
    frozen_runs, freeze_warnings = compute_freeze_state(
        upstream_max_date, has_invalid, period, previous
    )
    warnings.extend(freeze_warnings)
    if has_invalid:
        warnings.append("本次存在無法解析的公告日期，暫停累計停更證據")

    for w in warnings:
        print(f"⚠️ 警示：{w}")
    print(f"📅 上游最新公告：{upstream_max_date}；未前進區間數：{frozen_runs}（{period}）")

    payload = build_payload(
        datasets, now=now, upstream_max_date=upstream_max_date,
        frozen_runs=frozen_runs, last_observed_period=period,
    )
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
