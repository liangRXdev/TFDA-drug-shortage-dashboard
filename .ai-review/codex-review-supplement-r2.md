# Codex 獨立覆審原始輸出：第二輪（增量 S 修正後）

- 審查日期：2026-10-26
- Codex：codex-cli 0.153.4，model `gpt-6-astra`，codex plugin 1.0.6 `task --background`（唯讀），job `task-mvowqhh5-l86vjb`
- 審查範圍：整個 repository，重點為修正 commit `34054ca..5250f5a` 與增量 S
- commit：`5250f5a`
- prompt：`.ai-review/codex-prompt-supplement-r2.md`（新增區塊 0 修正驗證＋第一輪 prompt 全文＋規格）

> 以下為 Codex 輸出原文，未修飾、未刪改。

---

**需修正後合併。** 核心修正大多已落地，但前檔契約仍有跨端落差、非法 base 仍可被信任，且部分已標示完成的驗收尚未驗到承諾的性質。

審查版本：`5250f5a`；核對 `34054ca..5250f5a` 修正及增量 S。全程未修改檔案；完成原始碼、測試與證據審查，以及記憶體內 TS 反例驗證。未重跑會寫入檔案的 pytest、vitest、build，因此不將文件記載的全綠結果視為本輪實測。

## 0. 修正驗證

下表「已修」表示原問題已在實作與相關斷言中修補，未發現該修法的新問題；「部分」的剩餘問題於後續區塊詳述。共用問題的 S-* 編號併列，避免重複報告。

| 原編號 | 本輪判定與修正後證據 |
|---|---|
| R1、S-D10、S-6.1、S-B8 | **部分**：缺失 base 已停止信任，但非法時間尾碼仍可通過，見 N1。`src/lib/supplement.ts:207`。 |
| R2、S-6.2 | **已修原反例**：日期上限、證號、案件編號及編號對應已驗；正式 loader 有正反例。`src/lib/supplement.ts:106`、`src/lib/supplement.test.ts:453`。 |
| R3、S-D4、S-6.3c | **部分**：已建立共用前檔／輸出 validator，但仍接受 TS 會拒收的內容，見 N2。`scripts/supplement_scraper.py:695`、`:754`。 |
| R4、S-6.3d | **實作已修，驗收未閉合**：timer、focus、visibilitychange 與 `now` dependency 已接上；新測試仍不能偵測 App 接線被移除，見 T-R2。`src/App.tsx:89`、`:103`、`:112`。 |
| R5、S-D7 | **已修**：精確比較、`<br>` 換行及整段 trim 均有針對性斷言。`scripts/supplement_scraper.py:383`、`:407`；`scripts/test_supplement_scraper.py:338`、`:346`。 |
| R6、S-6.3a、S-A5 | **已修**：空節點須有正確文字，否則 error。`scripts/supplement_scraper.py:304`。 |
| R7、S-6.3b | **已修補抓端**：要求 200、HTTPS、正確 host／path／category；假 session 已走真正 client。`scripts/supplement_scraper.py:465`；`scripts/test_supplement_scraper.py:411`、`:416`。 |
| R8 | **已修**：比較單位集中至 `compare_unit()`，兩端 caller 共用。`scripts/supplement_scraper.py:560`、`:571`、`:576`。 |
| T1、S-D11、S-A11 | **發布內容部分已修**：真實 Git 測試比對遠端完整字串及 rebase 後 base；不再只驗 commit 訊息。排程 XML 仍明列待人工。`scripts/test_update_supplement.py:195`、`:203`、`:219`；`SMOKE_TEST.md:29`、`:43`。 |
| T2、S-A1、S-A4 | **已修主要缺口**：易安穩完整原文、第四筆失敗及同日修訂完整流程均已加入。`scripts/test_supplement_scraper.py:250`、`:912`、`:929`。 |
| T3、S-D8、S-A2、S-A12 | **部分**：重試來源與跨類移動已補；完整沿用與部分 orchestration 反例仍未補齊，見 T-R1。`scripts/test_supplement_scraper.py:949`、`:974`、`:985`。 |
| T4、S-B1 | **部分**：新增清洗後 ID、供應狀態、證號斷言與補抓輸入不可變性；仍未完整驗兩階段資料列，見 T-R3。`src/lib/supplement.test.ts:118`。 |
| T5、S-B4 | **部分**：純橫幅元件渲染與 F 並存已驗；App 接線、各契約情境的實際渲染未閉合，見 T-R2。`src/StatusBanners.test.tsx:26`。 |
| T6 | **部分**：TS 正式入口反例有效；Python 前檔反例仍漏掉「合法曆日但過遠未來」與 metadata 型別，見 N2。`scripts/test_supplement_scraper.py:771`；`src/lib/supplement.test.ts:464`。 |
| S-A3 | **部分**：新增完整沿用測試只覆蓋 s2，且 supersedes 為空；原 s3 破損列案例仍只比 additions／成功時間。見 T-R1。`scripts/test_supplement_scraper.py:544`、`:798`。 |
| S-A6 | **已修接受部分**：兩個換行的主檔反例已加入。接受 A6 可在純函式層驗差集；同日流程另由 A1 補足。`scripts/test_supplement_scraper.py:996`、`:929`。 |
| S-A7 | **部分**：英文全形引號仍未出現在新增向量，見 T-R4。`scripts/test_supplement_scraper.py:1003`。 |
| S-A8 | **已修主要缺口**：`main()` 缺檔 exit 1 已驗，其他主檔錯誤由共用 `MainFileError` 路徑覆蓋。`scripts/test_supplement_scraper.py:649`、`:1016`；`scripts/supplement_scraper.py:872`。 |
| S-A9 | **未完全修好**：成功快照測試仍只驗少數欄位；新增 validator 本身也不完整，見 N2、T-R4。`scripts/test_supplement_scraper.py:692`。 |
| S-A10 | **已修**：Python 產出與 committed fixture 完整比較，TS 經 loader／清洗驗證缺藥保留。`scripts/test_supplement_scraper.py:1052`；`src/lib/supplement.test.ts:498`。 |
| S-B3 | **部分**：同日新版文字已驗；承諾併入靜態測試的徽章渲染未加入，見 T-R2。`src/lib/supplement.test.ts:186`；`src/App.tsx:442`。 |
| S-B5 | **部分**：日期函式與入口已有反例；常駐 App 跨門檻仍未被測試真正觸發。`src/lib/supplement.test.ts:280`。 |
| S-B6 | **仍未完成畫面驗收**：loader／清洗結果有測；兩檔完成順序未測 App。不能以程式結構檢視等同 B6 驗收，見 T-R2。`src/App.tsx:70`；`src/lib/supplement.test.ts:322`。 |
| S-B7 | **未修驗收缺口**：新增 `StatusBanners` 測試未包含導覽或區塊計數。`src/lib/supplement.test.ts:342`；`src/StatusBanners.test.tsx:26`。 |
| S-B9 | **維持明示待補**：只有 key 函式測試；不計為互動驗收完成。`src/lib/supplement.test.ts:431`。 |
| S-C1 | **未達宣稱完成**：新腳本確實獨立計算差集，但案件對應及逐列證據仍不足，見 S-R1。`.ai-review/c1_independent_check.py:118`。 |
| S-C2 | **維持待執行、非阻擋**；未發現本輪新增的 probe workflow。 |
| S-C3 | **條款已修，人工驗收未完成**。`.ai-review/plan-supplement.md:243`、`:274`。 |
| S-C4 | **#5／#6 紀錄更正已完成**，新紀錄明列非空恢復公告及同日修訂；本輪未獨立重跑瀏覽器。離線等項仍待補。`SMOKE_TEST.md:34`、`:37`、`:43`。 |

## 1. Code review

### N1 — 非法 base 時間仍可被當作可信版本／Medium

**位置：** `src/lib/supplement.ts:140`、`:207`；`src/lib/dataPipeline.ts:84`。

`baseStatus()` 仍使用寬鬆的 `parseLastUpdated()`：regex 沒有結尾錨點，因此接受合法前綴後接任意內容。

本輪以現行主檔／補抓檔，僅將 s3 base 改成：

```text
2026-10-23 04:53:03garbage
```

實際得到：

```text
isSupplementData = true
trusted = true
hidden = 1
```

R1 的「未知或無效版本一律不可信」尚未完整成立。新增測試只覆蓋 `null`、`bad` 和錯誤型別，**只解析合法前綴的弱化實作仍能通過**。

**建議：** 補抓 base 使用完整格式與真實時間驗證，或先嚴格驗證再呼叫既有 parser；不必改動 N2 清洗規則。新增非法尾碼、超界時分秒反例，均須停止 supersedes 與 s2 additions。

### N2 — Python 前檔／輸出契約仍弱於 TS，R3 故障隔離問題仍存在／Medium

**位置：** `scripts/supplement_scraper.py:703`、`:744`、`:779`、`:852`；`src/lib/supplement.ts:114`、`:141`。

兩個具體反例：

- 前檔 addition 日期改為 **`2099/01/01`**：Python 只驗真實曆日，沒有未來上限，因此仍可沿用；TS 會拒收整份補抓檔。
- 前檔 `base.upstream_max_date = 123`：Python 未驗該欄，TS 明確拒收。

若該次 s2 失敗而沿用上述內容，即使 s3 成功抓到新缺藥，Python 的最終檢查仍可通過，前端卻整份拒收。原本 R3 的跨類連帶失效尚未消除。

現有污染測試使用 **`2099/13/01`**，驗到的是不存在的月份，**完全沒有未來日期檢查的實作仍會通過**。

**建議：**

- 前檔與輸出 validator 接收明確的執行時間，驗未來上限及 frontend 會檢查的 metadata 型別。
- 將這兩個反例加入「讀前檔 → 某類失敗沿用 → 其他類成功 → 正式 TS loader」驗證。
- 保留規格規定的「壞前檔整份視同首次」，不要改成放寬 TS 驗證。

另有修法引入的故障範圍問題：`load_main()` 在 `:673` 只驗逐欄字串；若主檔錯誤日期進入 supersedes，最後 `output_problems()` 才於 `:855` 整批拋錯，其他類的有效結果及 error 快照均不發布。應把可預期的來源契約錯誤提前歸入明確的主檔不可用或單類 error 路徑。

### 重複實作

**R8 已消除原重複。** 排除測試、validator 及規格允許的 Python／TS 雙份正規化後，本輪未確認其他需新增列報的重複規則問題。

## 2. Test gap analysis

### T-R1 — A2／A3／A12 的沿用與整體流程仍可假綠燈／Medium

**位置：** `scripts/test_supplement_scraper.py:544`、`:798`、`:852`、`:866`、`:954`、`:974`。

仍有以下缺口：

- 新 A2 流程案例只比 additions，沒有比 `last_success_at`、`success_run_id`、base、supersedes 等完整成功結果。
- A12(a)、A12(b) 從沒有前檔開始；**遇到不一致就清空前檔結果**的實作仍可通過。
- A12(d) 仍只比較 `_signature()`；**orchestration 不使用這個 signature**，該測試也會通過。
- A3 的完整沿用補測使用 s2 且 supersedes 為空，無法驗證非空 supersedes 沿用。

**建議：** 先建立包含非空 additions／supersedes 的成功前檔，再以不同執行時間注入各種失敗，完整比較應沿用欄位；A12 四種差異均走 `run()`。

### T-R2 — 新 UI 測試沒有驗到 App 接線、計數與徽章／Medium

**位置：** `src/lib/supplement.test.ts:292`、`:322`、`:342`；`src/StatusBanners.test.tsx:28`；`src/App.tsx:89`、`:237`、`:442`。

目前仍能通過的弱化實作包括：

- 刪除 App 的 timer／focus／visibilitychange，只保留 `trustExpiresAt()`：新 R4 測試仍綠，因為測試自行呼叫 `applySupplement()` 兩次。
- App 不傳 `merged` 給橫幅：純 `StatusBanners` 測試仍綠。
- 顯示錯誤計數或移除補抓徽章：新增靜態測試完全不會觸及。
- 改壞兩檔載入接線：B6 的 loader 測試仍綠。

**建議：** 加入 App 層 fake timers／受控 fetch 測試；計數與徽章可抽成純元件後靜態渲染，不必為此大改 UI。

**對主持人判定的異議：** §9 明示延期的是 **B9 互動測試**，沒有把 B6 完成順序、B7 畫面計數一併延期。以「程式結構可確認」取代其明列驗收，理由不足；維持 **Medium、未完成**。

### T-R3 — B1 仍未完整比較兩階段資料列／Medium

**位置：** `src/lib/supplement.test.ts:118`。

清洗前只比較 ID；清洗後雖新增供應狀態與證號，仍未比較公告日期、品名、來源及 theme。

例如保留 ID／證號／文字，但改壞公告日期或品名，仍可能通過這組共用 fixture 測試。這些欄位會影響月份分組、案件身分與後續比對。

**建議：** 兩階段均比較包含日期、品名、證號、供應狀態及來源的明確投影；清洗後另比 theme。預期值保持獨立寫定。

### T-R4 — 少數宣稱補齊的驗收仍未落實／Low

**位置：** `scripts/test_supplement_scraper.py:692`、`:1003`；`scripts/test_update_supplement.py:191`、`:203`。

- **A9：** `test_a9_success_is_complete_valid_snapshot` 仍只驗 schema、類別鍵與 run_id；遺漏 `scanned`、`excluded_no_license` 等欄位仍可通過。
- **A7：** 新向量包含 ASCII 英文引號與中文「」，沒有規格指定的英文全形引號。
- **A11(b)：** 真實 Git 的 exit 0 案例發布的仍是 `SNAPSHOT_ERROR`，未獨立建立「三類全 ok」的有效快照。

**建議：** 分別補完整成功 schema、實際全形引號向量，以及合法全 ok／部分 error 快照的逐位元發布比較。

## 3. Dependency audit

| 位置／嚴重度 | 尚未解決事項與建議 |
|---|---|
| `package-lock.json:9047`／**Medium** | Vite 8.0.8 仍在 Windows `server.fs.deny` bypass 影響範圍。符合特定 dev server 暴露條件才可利用，不能宣稱 Pages 靜態站可直接被利用。另案升級至受維護修補版本並驗 build／PWA。[官方公告](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff) |
| `package-lock.json:9254`、`:9327`／**Low** | Vitest／mocker 3.2.7 仍在已知任意檔案讀取問題影響範圍；本 repo 未確認啟用可利用的公開 mocker 路徑。另案升級合理，但不能標記已修。[官方公告](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9) |
| `.github/workflows/update_data.yml:34`／**Low** | 既有未使用的 pandas 安裝仍存在，另案移除。 |

**D-3 已修直接依賴版本一致性：** `scripts/register_supplement_task.ps1:5` 與 `scripts/update_supplement.py:20` 已指定 `requests==2.34.2`。該版本存在，授權為 Apache-2.0；固定 requests 本身不等於鎖住所有傳遞依賴。[PyPI metadata](https://pypi.org/pypi/requests/2.34.2/json)

接受既有 npm 問題另案處理、不單獨阻擋 S；本輪未重新執行完整 vulnerability audit，不沿用「17 項」作為目前已驗證總數。

## 4. 規格符合度稽核

### S-R1 — C1 的「單位一致」被擴張宣稱成完整逐列核對通過／Medium

**規格：** `.ai-review/plan-supplement.md:241`，C1 要求逐列案件編號、日期、品名、證號、指紋，以及差異目標核對。

**實作：** `.ai-review/c1_independent_check.py:118`、`:122`、`:125`；`.ai-review/c1-check-2026-10-26.md:6`。

仍有兩個實質缺口：

1. `got_add` 不含 `_案件編號`，也沒有另建案件對應檢查。只要保留內容單位，將 addition 的案件編號與 `編號` 一起換成另一個合法數字，核對仍會判「一致」。
2. 報告只保存筆數及差集摘要，未保存三類完整逐列觀測、內容指紋及各類 base，不能追溯宣稱的 237 筆相同內容。

**建議：** 保留現有 Counter 比較，另核對 addition 的案件身分與來源列；保存完整逐列 JSON／JSONL 觀測、各類 base、run_id 與時間，再由摘要引用該產物。在此之前，將「C1 通過」改成精確的已完成範圍。

### 其餘仍未符合的條款

| 規格條款與位置 | 實作位置／嚴重度 | 缺口及相容修法 |
|---|---|---|
| D10、§6.1：`plan-supplement.md:110` | `src/lib/supplement.ts:207`／**Medium** | 無效 base 仍可允許隱藏；依 N1 補嚴格時間驗證。 |
| D4、§6.2／§6.3：`:104`、`:164` | `scripts/supplement_scraper.py:703`、`:744`／**Medium** | 不可用前檔仍被沿用，TS 整份拒收；依 N2 對齊契約。 |
| A2／A3／A12：`:194`、`:195`、`:227` | `scripts/test_supplement_scraper.py:954`、`:974`／**Medium** | 完整沿用與 orchestration 證據不足；依 T-R1 補非空前檔案例。 |
| B1：`:230` | `src/lib/supplement.test.ts:118`／**Medium** | 兩階段完整列身分未驗；依 T-R3 補明確投影。 |
| B3–B7：`:232` 至 `:236` | `src/StatusBanners.test.tsx:26`、`src/lib/supplement.test.ts:280`／**Medium** | UI 接線、計時器、徽章及計數仍未完成承諾；依 T-R2 補驗收。 |
| C3：`:243`、`:274` | 驗收紀錄仍為待使用者／**Medium** | 條款已可執行，但沒有本人逐字核對完成證據；不可當作已通過。 |
| C4：`:244` | `SMOKE_TEST.md:25`、`:36`、`:43`／**Medium** | 離線有／無快取、過期快取仍未實測；補瀏覽器驗收並記錄結果。 |

D1–D3、D5–D9、D12 未確認其他新增規格偏差；不要求放寬保守守門，也不要求修改既有 `cleanSupplyData`。C2 與已明示延期的 B9 保持待辦，不冒充完成。

**需修正後合併。**

Codex session ID: 01a17702-d60a-7cb2-9bcd-334a612047f8
Resume in Codex: codex resume 01a17702-d60a-7cb2-9bcd-334a612047f8
