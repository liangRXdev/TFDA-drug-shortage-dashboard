# 獨立覆核判定（Reviewer of Reviewers）

- **覆核日期**：2026-07-21
- **覆核者**：Claude（主持人），逐項回讀原始碼與資料驗證
- **審查範圍**：整個 repository
- **Commit hash**：48289401b636363b70f33d6439531b066684d8a0
- **對象**：Codex 原始報告見 `codex-review.md`

## 覆核方法

每一項都回讀 Codex 引用的 `file_path:line_number`，並對 `public/data/supply_status_latest.json`（651 筆）實測關鍵爭點：換行字元型態、105 sentinel、extractAlternative 命中率、106 重複列、依賴 deprecated 狀態。**Codex 引用的行號與檔案全部正確，未發現幻覺（無不存在的 API／函式／檔案）。**

## 統計

- **接受：26**
- **部分接受：3**（CR-04、CR-11、DA-02 — 問題屬實但嚴重度需調整）
- **拒絕：0**

---

## 1. Code review

| # | 項目 | Codex 嚴重度 | 判定 | 理由（含實證） |
|---|------|--------|------|------|
| CR-01 | ETL fail-open：API 失敗當空資料發布 | Critical | **接受** | `scripts/fetch_fda_data.py:17-19` 例外一律回傳 `[]`；`main()` 第 39-40 行無條件覆寫檔案並更新 `last_updated`；`update_data.yml:37` 的 `git diff --quiet ... || commit && push` 會因空資料造成 diff 而 commit。前端 `App.tsx:149-151` 讀空陣列 → nav 顯示「無替代 0」。符合威脅模型最高權重（污染資料入口）。修法（fail-closed＋暫存原子替換＋sanity check）相容零後端架構。**列為必修第一。** |
| CR-02 | API 回傳無 schema/欄位驗證 | High | **接受** | `fetch_fda_data.py:14` `response.json()` 直接寫入。實測 105 資料集確含 sentinel 列 `編號="沒有資料"`、其餘欄位皆 `null`，目前僅靠前端 identity filter（`App.tsx:181`）剛好排除。合法但欄位改名／型別變更／截斷都不會被擋。與 CR-01 同屬資料入口，必修。 |
| CR-03 | 「缺藥 N 天」實為距公告更新日天數 | High | **接受** | `App.tsx:184` `_days = getDaysDiff(公告更新時間)`，`App.tsx:504` 標示「缺藥 {d} 天」並據此做 urgency 分級（`d>30` 紅／`d>=14` 黃）。公告更新時間非短缺起始日，且公告會因狀態修訂而更新，直接誤導臨床急迫度。屬資料正確性，必修。缺可信起始日時應改標「公告距今 N 天」。 |
| CR-04 | 殭屍清除用非嚴格 `new Date()`，異常日期靜默失效 | High | **部分接受** | 機制屬實：`App.tsx:157` 首筆無效日期存入 `resolvedDates` 後，因 `x > NaN` 恆為 false 無法被有效日期取代；`App.tsx:169/177` 過濾式 `resTime && ...` 中 `NaN` 為 falsy → `!(false)`=true → 殭屍品項被保留。**但嚴重度略高估**：`new Date("YYYY/MM/DD")` 雖非 ECMAScript 保證格式，主流瀏覽器（Chrome/Firefox/Safari/Edge）皆一致解析為本地日期；實測現有 650 筆有效日期全為 `YYYY/MM/DD`，NaN-poisoning 需 CR-02 未擋下的壞資料才觸發。**實際風險等同 Medium，仍建議修**：抽出嚴格 `parseTfdaDate()`＋由 ETL（CR-02）先擋無效日期。 |
| CR-05 | PWA StaleWhileRevalidate 讓當次畫面顯示舊 JSON | High | **接受** | `vite.config.ts:29-37` 對 `supply_status_latest.json` 用 `StaleWhileRevalidate`，首次載入即交付舊 cache，背景更新後 React 不會自動 refetch；`PwaBanners.tsx:58` `needRefresh` 只反映 SW/app shell 換版，不代表 runtime-cached JSON 更新，純資料更新甚至不觸發 banner。對每週更新、時效敏感的臨床資料，High 合理。建議 JSON 改 `NetworkFirst` 或背景更新後 broadcast 通知 React。 |
| CR-06 | repo 內資料已逾每週更新週期約 60 天 | High | **接受** | 實測 `supply_status_latest.json:2` `last_updated=2026-05-22`，今 2026-07-21，約 60 天，與 `update_data.yml:4` 每週五 cron 不符。**補充根因**：GitHub 對 60 天無活動的 repo 會自動停用 scheduled workflow，極可能是排程已被停用——這使 freshness gate（逾 8-10 天即失敗告警＋前端過期 banner）更為必要。屬資料正確性，必修。 |
| CR-07 | 替代藥 regex 把非藥名內容標成 💡 替代建議 | Medium | **接受** | 實測 `App.tsx:41` regex 對 266 筆 104 僅命中 10 筆，且多為雜訊：「與缺藥品項成分不盡相似」「替代」「(詳述如下)」「藥品圖卡連結…URL」「的病人」。這些經 `App.tsx:508` 顯示為 💡 tag，視覺上像已確認替代品，對臨床有誤導。近期 commit `cf1710e` 已補「之」但「的病人」仍漏。Codex 未要求收緊 regex（尊重高召回取捨），改提 confidence/provenance 顯示，作法正確。 |
| CR-08 | 完全重複事件未去重，膨脹卡片與統計 | Medium | **接受** | 實測 106 資料集存在 1 組完全重複列（`衛署菌疫輸字第000935號 / 2024/08/20 ×2`），且產生 1 組 `許可證字號+日期` 碰撞 → `App.tsx:476` React key（以許可證字號優先）重複。目前僅 1 組、影響小，但屬會隨資料成長的實質缺陷。去重建議在 ETL 依「資料集＋證號＋日期＋正規化狀態」為之、勿只依證號（避免併掉不同 episode），判斷正確。 |
| CR-09 | 「最新十筆」受排序模式影響且忽略篩選／搜尋 | Medium | **接受** | `App.tsx:203-221`：先依 `sortMode` 排序再 `slice(0,10)`，故選「名稱 A-Z／缺藥最久」時「最新十筆」並非最新；該分支 `if(showLatestTen)` 完全略過 search/status/year/month。`sortMode` 與搜尋框未被 `disabled`（僅 `App.tsx:315/321/325` 三個 select 停用），語意矛盾。屬實。 |
| CR-10 | 前端無 `res.ok` 與 runtime schema 防線 | Medium | **接受** | `App.tsx:138-143` 只 `res.json()`，未檢查 `res.ok`，json 直接當 `SupplyData`。404 回 HTML 會於 `json()` 拋錯落入 catch（尚可），但 200＋錯誤 JSON 會在後續 `data.datasets[...]` 造成未捕捉例外或錯誤統計。作為 ETL fail-closed 之外第二道防線，合理。 |
| CR-11 | ETL 時間戳缺時區 | Medium | **部分接受** | 屬實：`fetch_fda_data.py:25` 用 naive `datetime.now()`，GitHub runner 為 UTC，`App.tsx:271` 直接當文字顯示，台灣使用者看到少 8 小時。**但嚴重度高估**：僅為顯示時間偏移，不直接影響缺藥判斷或臨床決策，實際等同 **Low**。修法（存 ISO 8601 UTC＋前端以 `Asia/Taipei` 格式化）簡單且值得做。 |
| CR-12 | `/\\r\\n/g` 誤匹配字面反斜線 | Low | **接受** | **實測確認**：JSON.parse 後 `供應狀態` 內含真實 `\r\n` 控制字元（非字面四字元），故 `App.tsx:47/529` 的 `/\\r\\n/g`（匹配 `backslash r backslash n`）永不命中、replace 為 no-op。`extractRecoveryTime`（`App.tsx:49`）字元類未排除 `\n`，可能跨行誤抓。詳情區因 CSS 處理換行，視覺影響有限（Codex 已註明）。應改 `/\r?\n/g`。 |
| CR-13 | 「項數／件數」事件模型未明確定義 | Low | **接受** | `App.tsx:81` `uniqueDrugCount` 依證號或品名去重，但 `App.tsx:368` 「通報件數」與圖表按 row 累加；重複列、同證號多 episode、當前篩選都會改變數字，易被誤讀。屬文件／UX 清晰度，Low 合理。 |
| CR-14 | 型別在統計與 Section 邊界以 `any` 繞過 | Low | **接受** | `App.tsx:83` `Record<string, any>`、`App.tsx:329` `as any`、`App.tsx:422` `Section({...}: any)` 屬實，違反使用者全域規則「不用 any、props 須定義 interface」。可維護性，Low。 |

### 安全性補充（覆核同意）
全檔無 `dangerouslySetInnerHTML` 或其他繞過 React escaping 的渲染路徑，TFDA 文字皆於 JSX text node 輸出。依威脅模型（無認證、無機密、經 escaping），理論性 XSS 不列高風險——與 Codex 一致。

---

## 2. Test gap analysis

現況確認：`package.json` 無 `test` script，全 repo 無測試檔。以下皆**接受**，惟務實排序：純函式單元測試（TG-03/04）成本最低、價值最高，應優先；PWA/Playwright（TG-05）為較重投資，可後置。

| # | 項目 | Codex 嚴重度 | 判定 | 理由 |
|---|------|--------|------|------|
| TG-01 | ETL fail-closed／原檔保留測試 | Critical | **接受** | 對應 CR-01，`fetch_fda_data.py:12` 需 mock `requests.get` 驗證單一／全部端點失敗時非零退出、正式 JSON 不變。與必修第一項綁定。 |
| TG-02 | schema／sentinel／筆數驟降測試 | High | **接受** | 對應 CR-02，需驗證「沒有資料」sentinel 與「抓取失敗」可區分、結構錯誤不被誤判為正常空集。 |
| TG-03 | 殭屍事件×日期順序矩陣測試 | High | **接受** | 對應 CR-04/CR-08，將清洗抽為 pure function 後測 shortage→resolved、resolved→新 shortage、同日、多 episode、空證號、無效日期。**最高性價比，建議優先。** |
| TG-04 | 缺藥天數×日期邊界測試 | High | **接受** | 對應 CR-03，注入固定 clock，測純日期差與「公告距今」語意；閏年／月底／未來日期邊界。**建議優先。** |
| TG-05 | PWA 資料更新／離線退回測試 | High | **接受** | 對應 CR-05，需 Playwright 驗證線上優先顯示最新 `last_updated`、離線才用 cache 並標示時間。投資較重，可後置。 |
| TG-06 | regex 高召回×低信心顯示 regression | Medium | **接受** | 對應 CR-07，以去識別化真實公告 fixture 分類測試，重點在避免低信心片段被當已確認藥名。 |
| TG-07 | 去重與統計不變量測試 | Medium | **接受** | 對應 CR-08/CR-13，驗證完全重複只計一次、合法不同 episode 保留。 |
| TG-08 | 排序／篩選／最新十筆組合測試 | Medium | **接受** | 對應 CR-09，優先覆蓋 latestTen×name/longest sort、搜尋中切換、同日穩定排序。 |
| TG-09 | 前端錯誤／過期資料提示測試 | Medium | **接受** | 對應 CR-06/CR-10，驗證 404／錯誤 JSON／逾更新週期顯示警示而非 render 成零筆正常資料。 |

---

## 3. Dependency audit

| # | 項目 | Codex 嚴重度 | 判定 | 理由 |
|---|------|--------|------|------|
| DA-01 | 無法完成線上 vulnerability audit | Medium | **接受** | Codex 誠實聲明受限網路無法連 `registry.npmjs.org`，故無法確認 2026-07-21 當下 advisory。本覆核環境同樣離線，未能獨立跑 `npm audit`。建議（CI/Dependabot 跑 lockfile scan，Critical/High 擋 deploy）為有效流程改善。 |
| DA-02 | Python 依賴未固定且裝不必要 pandas | Medium | **部分接受** | 屬實：`update_data.yml:24` 裝 `requests pandas`，而 `fetch_fda_data.py` 僅 import `requests/json/os/datetime`，pandas 未用。**嚴重度略高**：屬 CI 供應鏈衛生／可重現性，非直接資料正確性，實際 **Low-Medium**。建議移除 pandas＋以 requirements pin（含 hash）。 |
| DA-03 | transitive `glob@11.1.0` deprecated | Low | **接受** | 實測 `package-lock.json:4984-4988` `glob@11.1.0` 帶 deprecated 訊息（明指含公開漏洞），由 `workbox-build` 引入、build-time only，未進瀏覽器 runtime，Low 合理。建議隨 `vite-plugin-pwa`/Workbox 升級解決，勿逕自 override major。 |
| DA-04 | `source-map@0.8.0-beta.0` deprecated | Low | **接受** | 實測 `package-lock.json:7526` 版本確為 `0.8.0-beta.0`，屬 Workbox build chain 的 build-time 依賴，無臨床邏輯影響，Low。 |
| DA-05 | deploy 用 `npm install` 而非 `npm ci` | Low | **接受** | `deploy.yml:40` 確為 `npm install`。已有 lockfile，改 `npm ci` 提升 CI 可重現性。 |
| DA-06 | GitHub Actions 僅固定 major tag | Low | **接受** | `update_data.yml`／`deploy.yml` 用 `@v4`/`@v5` 可移動 tag，且 update workflow 具 `contents: write`。建議 pin 至 commit SHA＋Dependabot 更新。供應鏈防護，Low。 |

### 授權檢查（覆核同意）
直接依賴授權（React/ReactDOM/Recharts/Vite/vite-plugin-pwa=MIT、TypeScript=Apache-2.0）無商用衝突；`@emnapi/*` 缺 license metadata 若要出 SBOM 需再查證。與 Codex 一致，無異議。

---

## 覆核總評

- Codex 本次品質高：**零幻覺**，行號精準，且正確吸收了「專案前提」——把最高嚴重度給了**資料入口污染（CR-01/02）**與**資料正確性（CR-03/06）**，而非理論性 XSS，符合本專案威脅模型。
- 僅 3 項需調整嚴重度（CR-04、CR-11 高估；DA-02 略高），無誤判需拒絕。
- **必修優先序見對話摘要。**
