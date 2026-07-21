# 處理進度紀錄（Remediation Log）

> 本檔記錄依 `verdict.md` 判定後實際的修復動作與測試佐證。
> `verdict.md` 保留為原始獨立判定（稽核用），不因後續修復而更動。

- **日期**：2026-07-21
- **測試狀態**：Vitest 71 passed／pytest 20 passed（共 91）；`npm run build` 綠；`eslint` 乾淨

---

## 批次 5（第一 slice）：純函式抽出 + 高價值單元測試

| 動作 | 檔案 |
|---|---|
| 抽出零 React／零 Vite 相依的純函式模組 | `src/lib/dataPipeline.ts` |
| characterization + regression 測試 | `src/lib/dataPipeline.test.ts`（52） |
| Behavior-preserving refactor（改為 import） | `src/App.tsx` |
| 加 `test`/`test:watch` script + vitest devDep | `package.json` |

## 批次 2：ETL fail-closed（CR-01 / CR-02）+ TG-01/02

| Finding | 狀態 | 修法 | 佐證 |
|---|---|---|---|
| **CR-01**（Critical）ETL fail-open | ✅ 已修 | 重寫 `fetch_fda_data.py`：任一端點失敗即 raise → `main()` `sys.exit(1)`，**不覆寫**原檔；全部成功才 `os.replace` 原子替換；新增「全空拒絕發布」sanity check | pytest `TestRunPreservesOriginalOnFailure`（3）、`TestFetchAllFailClosed`（4） |
| **CR-02**（High）無 schema 驗證 | ✅ 已修 | `validate_and_normalize()`：強制 list、欄位型別檢查、`沒有資料` sentinel 與抓取失敗明確區分、空陣列無 sentinel 判異常 | pytest `TestValidateAndNormalize`（7）、`TestCheckSanity`（4） |
| **TG-01** ETL fail-closed 測試 | ✅ 補齊 | 單一/全部端點失敗、連線錯誤、JSON decode、原檔保留、`main` 非零退出 | `scripts/test_fetch_fda_data.py` |
| **TG-02** schema/sentinel/筆數 | ✅ 補齊 | 合法/非 list/sentinel/空陣列/型別錯/null 欄位/驟降告警 | 同上 |

備註：`update_data.yml` 的 commit step 在 fetch step 非零退出時本就不會執行（GitHub Actions 預設 fail-fast），故 fail-closed 於 CI 層自動生效，無需改 workflow。`pandas` 未用（DA-02）仍在，屬批次 4，未動。

## 批次 3（部分）：前端純函式 bug 修正

| Finding | 狀態 | 修法 | 佐證 |
|---|---|---|---|
| **CR-04**（High→實 Medium）日期 NaN-poisoning | ✅ 已修 | 新增嚴格 `parseTfdaDate()`（regex + 範圍/rollover 驗證，無效回 null）；`getDaysDiff`、`cleanSupplyData` 殭屍比較、`sortRecords` newest 全改用之，無效日期跳過不寫入 | vitest `parseTfdaDate`（7）、getDaysDiff CR-04、cleanSupplyData CR-04 |
| **CR-12**（Low）`\r\n` replace no-op | ✅ 已修 | `extractRecoveryTime` 先 `replace(/\r\n/g,'\n')` 正規化，字元類排除 `\n` 防跨行擷取 | vitest extractRecoveryTime CR-12 |

原本鎖定「錯誤現狀」的 3 個 `TODO` 測試已翻轉為 regression guard（斷言修正後的正確行為）。

## 批次 3（續）：CR-05 / CR-06

| Finding | 狀態 | 修法 | 佐證 |
|---|---|---|---|
| **CR-05**（High）PWA StaleWhileRevalidate 顯示舊 JSON | ✅ 已修 | `vite.config.ts` 對 `supply_status_latest.json` 改用 `NetworkFirst`（`networkTimeoutSeconds: 5`），線上優先取最新、離線才退回 cache | `npm run build` 後 `dist/sw.js` 確認含 `NetworkFirst` + `shortage-data-v1` |
| **CR-06**（High）資料時效無防線 | ✅ 已修（前端） | 新增 `parseLastUpdated`/`getDataAgeDays`/`isDataStale`（門檻 10 天，嚴格解析）；App.tsx 於逾期時顯示醒目紅色 `role="alert"` banner，標示「N 天前、以官方公告為準」 | vitest `data freshness (CR-06)`（7） |

**CR-06 營運面待辦（非程式碼）**：目前 checkout 的資料為 60 天前，最可能根因是 **GitHub 對 60 天無 repo 活動自動停用 scheduled workflow**。前端 banner 為使用者端防線，但**恢復每週更新需人工重新啟用 `update_data.yml` 的排程**（於 Actions 頁面 re-enable，或先 `workflow_dispatch` 手動觸發一次）。此屬 repo 設定操作，程式碼無法代勞。

## 批次 3（續）：CR-03

| Finding | 狀態 | 修法 | 佐證 |
|---|---|---|---|
| **CR-03**（High）「缺藥 N 天」語意誤導 | ✅ 已修 | App.tsx DrugCard 標籤改「公告距今 N 天」並加 `title` 說明「非缺藥起始日」；排序選項「缺藥最久」改「公告距今最久」；`getDaysDiff` 註解由 TODO 更新為「已修正」 | `tsc -b` 綠；`getDaysDiff` 行為未變，既有 TG-04 測試涵蓋 |

CR-03 為 UI 文案層修正（`getDaysDiff` 數值語意本就是「公告距今」，行為不變），無需新增單元測試。

## 批次 4：Medium 批次清理（CR-07/08/09/10/11/14）

| Finding | 狀態 | 修法 | 佐證 |
|---|---|---|---|
| **CR-07**（Medium）替代藥雜訊誤標為藥名 | ✅ 已修 | 不收緊擷取 regex（維持高召回），新增 `alternativeConfidence()`：high（含許可證號/Latin 藥名/◎ 標記）才顯示 💡 候選；low（URL/泛稱/過短）改顯示「ℹ️ 公告含替代資訊，請展開查看」 | vitest `alternativeConfidence (CR-07)`（4） |
| **CR-08**（Medium）完全重複列膨脹卡片與統計 | ✅ 已修 | `cleanSupplyData` 依「資料集＋證號＋日期＋供應狀態」去除完全重複列，不合併不同 episode；連帶消除 React key 碰撞 | vitest cleanSupplyData CR-08（2） |
| **CR-09**（Medium）「最新十筆」語意錯亂 | ✅ 已修 | 抽出 `selectVisibleRecords`：最新十筆固定依公告日期取前 10、忽略 sortMode/篩選；App 於該模式停用搜尋框與排序選項 | vitest `selectVisibleRecords (CR-09)`（4） |
| **CR-10**（Medium）前端無 res.ok/schema 防線 | ✅ 已修 | fetch 檢查 `res.ok`，並以 `isSupplyData()` type guard 驗證結構後才 setData | vitest `isSupplyData (CR-10)`（2） |
| **CR-11**（Medium）ETL 時間戳缺時區 | ✅ 已修 | `build_payload` 改用台灣時間（UTC+8）產生 `last_updated`，修正 -8 小時偏移 | pytest 既有成功路徑；格式不變（前端 parseLastUpdated 相容） |
| **CR-14**（Low）`any` 繞過型別 | ✅ 已修 | `sortMode` 用 `SortMode`、`Section` 定義 `SectionProps`，移除 2 處 `any`；eslint 由 2 error → 0 | `eslint` 乾淨 |

---

## 尚未處理（後續批次）

- **CR-13**（Low）統計術語「項/件」定義：純文案，未動。
- **TG-05**（PWA Playwright）：未補。
- **依賴類 DA-02/05/06**：未處理。
