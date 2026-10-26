# Codex 獨立覆審原始輸出（增量 S：dsms 公告頁補抓）

- 審查日期：2026-10-26
- Codex：codex-cli 0.153.4，model `gpt-6-astra`，codex plugin 1.0.6 `task --background`（唯讀，未加 `--write`），job `task-mvour0s2-hezx97`
- 審查範圍：整個 repository，重點為 `feat/dsms-supplement` 相對 `c822cd6` 的增量 S
- commit：`34054ca`
- prompt：`.ai-review/codex-prompt-supplement.md`（專案前提 (a)(b)＋規格 r5 全文）
- 註：第一次啟動（job `task-mvotyzgw-6lgxst`）因預設模型 `gpt-6.1-sol` 回 400 失敗，未產出內容

> 以下為 Codex 輸出原文，未修飾、未刪改。

---

**覆審結論：不建議合併。** 已重現 D10 基準驗證失效，以及不合法恢復公告被接受後隱藏缺藥列的問題；現有測試與驗收紀錄不足以排除這些漏報風險。

審查版本：`feat/dsms-supplement`，HEAD `34054ca`，比較基線 `c822cd6`。全程未修改檔案；執行了記憶體內的 TS 反例驗證，未執行會寫入產物的完整測試、build 或連網補抓。原有未追蹤檔案保持不變。以下「未發現違反」不代表已完成實機驗收。

## 1. Code review

### R1 — 缺失或無效的基準版本反而允許隱藏

**`src/lib/supplement.ts:116、175–179、263–264`；`scripts/supplement_scraper.py:619–637、679` / High**

- `base` 只驗證為 object 或 null；`mainOlderThanBase()` 遇到無法解析的基準時間直接回傳 `false`，被解讀成「沒有版本問題」。
- 使用目前主檔與補抓檔，在記憶體中將 s3 `base` 分別改成 `null`、`{}`、`{last_updated:"bad"}`，三種結果皆為：
  - `isSupplementData === true`
  - `trusted === true`
  - `hidden === 1`
- 若改成 `{last_updated:123}`，驗證仍通過，但執行時拋出 `s.trim is not a function`，無法依契約降級顯示主資料。
- Python 的 `load_main()` 也未驗證頂層 `last_updated`，可產生缺失基準的成功快照。

**建議修法：** 成功類別必須具有合法基準時間；無法確認版本相容時一律禁止 supersedes 與 s2 additions。驗證巢狀型別，讓損壞補抓檔回到既有紅色降級流程；主檔缺失必要基準時應在寫檔前中止。

### R2 — 前端逐筆驗證未落實 §6.2，非法恢復公告可造成漏報

**`src/lib/supplement.ts:91–105`；`src/lib/dataPipeline.ts:47–58、210–231` / High**

- additions 的證號只要求非空，案件編號只要求字串，未驗證 `編號 === dsms-<案件編號>`。
- 日期借用允許 `YYYY/M` 的通用解析器，未限制嚴格格式及未來日期。
- supersedes 的日期、證號及分類相關指紋條件也未完整驗證。
- 已重現：將主檔的一筆缺藥列構造成 s2 addition，日期設為 `2099/01/01`、案件編號設為 `not-a-number`、編號設為 `wrong-id`。前端仍判定合法且可信；經既有清洗後，原缺藥列消失，假的恢復列留下。

**建議修法：** 為補抓入口建立完整的 §6.2 語意驗證，使用台灣日期判斷未來上限，驗證案件編號與衍生編號對應、證號格式及各類 supersedes 契約。**不修改既有 zombie 規則**；應阻止非法輸入進入該規則。

### R3 — 前檔損壞仍被沿用，可能連帶丟失其他類的新公告

**`scripts/supplement_scraper.py:640–646、649–673`；`src/lib/supplement.ts:117–128、151` / High**

- 前檔只檢查 schema 數字及 categories 容器；沿用條件只確認 additions／supersedes 是陣列，未驗證其中資料或類別對應。
- 例如前檔 s2 的 additions 為 `[null]`，本次 s2 失敗，該內容仍會被沿用及發布。
- 前端隨後拒收整份補抓檔，本次成功取得的 s3／s4 新缺藥也一起失去；破壞 D4 的分類故障隔離。
- 若污染內容仍符合目前寬鬆 TS 驗證，則可能以錯誤類別或錯誤內容顯示。

**建議修法：** 沿用前先驗證完整前檔及逐筆契約；依 §6.3，schema 不符的前檔應視同首次執行，不沿用舊結果。發布前再驗證輸出契約。

### R4 — 開啟中的頁面不會隨時間撤銷 D10 信任

**`src/App.tsx:65–88`；`src/lib/supplement.ts:168–172、253` / High**

- `applySupplement()` 的目前時間被封在只依賴 `[data, supplement]` 的 `useMemo`。
- 若載入時資料為 2.9 天前，頁面保持開啟或 PWA 從背景恢復，超過 3 天後仍沿用原本的可信結果。
- 搜尋或排序即使造成重新渲染，也不會重算該 memo；舊公告繼續被隱藏，紅色過期警示不會出現。

**建議修法：** 將時鐘納入計算依賴，在新鮮度到期、頁面恢復可見及取得焦點時重新計算。可保持靜態站及既有資料來源，不需要後端。

### R5 — 詳情內容完整性檢查使用了較弱的比較語意

**`scripts/supplement_scraper.py:184–189、367–385` / Medium**

- 同一最新日期多列，使用 `norm(text)` 判斷一致；規格要求「內容完全相同」。例如 `藥A\n藥B` 與 `藥A藥B` 被當成相同並任選第一列。
- `display_text()` 對每一行使用 `rstrip()`，並非只去整段頭尾空白。
- `text_of()` 完全忽略 `<br>`；若合法 HTML 以 `<br>` 表示換行、沒有額外文字換行，替代藥清單會被接在一起，仍可成功發布。

**建議修法：** 分離「跨來源比較指紋」與「詳情原文完整性」。同日衝突使用保留內容的精確比較；HTML 換行明確轉換並避免既有 fixture 雙重換行；只去除整段頭尾空白。

### R6 — 空集合判定只認 element ID，不認「尚無資料」內容

**`scripts/supplement_scraper.py:295、303–313、323` / Medium**

- 只要列表內存在 `*_lbEmpty`，即視為合法空集合。
- 若該節點改成「系統維護中」「資料讀取失敗」，甚至內容空白，仍會被解讀成 `L = ∅`。
- 對主檔只有 1～3 筆的類別，全部 supersedes 可通過熔斷；三類均成功時即可誤藏公告。

**建議修法：** 同時確認正確類別、正確列表位置、唯一空狀態節點，以及明確的「尚無資料」文字；未知內容應 error。保留既有熔斷上限。

### R7 — HTTP 回應檢查未完全落實失敗契約

**`scripts/supplement_scraper.py:436–448` / Medium**

- `raise_for_status()` 不等同要求 HTTP 200；例如 206 帶合法外觀 HTML 仍可接受。
- 最終 URL 只核對 path 與 `s`，未核對 HTTPS 及 `dsms.fda.gov.tw`。
- 因而「非 200」「跳轉到非預期來源」未必觸發類別 error。

**建議修法：** 明確要求最終狀態為 200，核對 scheme、hostname、path 及類別參數；保留正常的 POST→302→GET 詳情流程。

### 重複實作

**R8 — 同一比較單位的組裝在 Python 內重複**

**`scripts/supplement_scraper.py:534–538` ↔ `scripts/supplement_scraper.py:541–546` / Low**

- `main_unit()` 與 `record_unit()` 各自實作「品名鍵＋日期，s3／s4 再加證號＋指紋」。
- 主檔名稱結構檢查確有必要，但其後的單位組裝相同。任一端增減欄位或漏做正規化，會把原本相同的公告誤算成替換，或漏掉修訂。

**建議修法：** 保留主檔專屬名稱驗證，將後續單位組裝交給單一函式。此項指同一 Python 執行環境內的重複，**不包含規格允許的 Python／TS 各一份正規化**。

## 2. Test gap analysis

### T1 — 「發布成功」實際只驗證 commit 訊息

**`scripts/test_update_supplement.py:17–45、54–87、118–124` / High**

- FakeRunner 的 `local`／`remote` 存放 commit message，沒有檔案內容。
- `test_partial_error_snapshot_still_published` 無法證明發布的是 error JSON。
- `test_retry_does_not_rewrite_supplement_file` 只限制後續指令為 pull／push，不能證明 rebase 後各類 `base` 保持不變。
- 排程測試只搜尋 `.ps1` 字串，連註解中的旗標也能使測試通過，未驗證 XML。

**建議修法：** 模擬 worktree、index、commit 與 remote 的實際 JSON，逐一比對發布內容及 base；另核對產生或匯出的排程 XML。

### T2 — 「保留所有替代藥」沒有驗證完整文字

**`scripts/test_supplement_scraper.py:225–238、273–289` / High**

- 摩法爾只驗開頭及不存在某段舊文字。
- 易安穩只驗六行 `◎` 與最後一行開頭；前五項被截短、替換或錯置仍可能通過。
- 同日衝突只測明顯不同的「甲／乙」，未測正規化後相同、原文不同。
- A4 未涵蓋「前三筆正常、第四筆壞」後整類回復前檔。
- FakeClient 繞過真正 `DsmsClient`，未驗證非 200、TLS、重新導向類別及來源檢查。

**建議修法：** 用獨立寫定的完整原文逐字斷言；新增上述 HTML／HTTP 反例，經完整分類流程驗證 state、差異及成功時間全部回復。

### T3 — A2／A12 多處只驗 helper，沒有驗證承諾的失敗結果

**`scripts/test_supplement_scraper.py:356–413、655–683` / Medium**

- A2 各反例只斷言 `scan()` 拋錯，未逐案驗證沿用前檔。
- `test_a2h_real_pager_group_jump` 只解析第 10 頁並看 `has_next`，沒有跨組請求。
- A12(d) 只比較兩個 `_signature` 不相等，未證明 orchestration 會重試及三類 error。
- A12(c) 重試後只驗 rows＝20，而第一次第一輪也是 20；錯用第一次觀測仍可能通過。
- 缺少 A12(b) 跨類移動情境。

**建議修法：** 使用內容彼此可區別的各輪快照，斷言完整 additions／supersedes、請求序列及沿用內容；不要只以筆數區分觀測來源。

### T4 — 共用 fixture 未驗證清洗後集合與內容

**`src/lib/supplement.test.ts:102–120`；`scripts/test_supplement_scraper.py:466–486`；`scripts/fixtures/supplement_cases.json:2` / High**

- B1 共用案例只比較清洗前的 `編號` 序列，未逐案驗證 `cleanSupplyData` 後集合及指紋。
- 只驗主檔未被修改，沒有驗補抓輸入。
- Python A6 使用自行重組的 `compute_case()`，不經 `process_category()`、詳情抓取或熔斷。
- A1(b)「同日修訂完整流程」因此沒有被 A6 純函式測試替代；唯一具名完整修訂流程是改日期案例。

**建議修法：** fixture 分別寫定合併前後／清洗後的完整期望列與指紋，兩端各自核對；補同日修訂經詳情抓取的整合測試。

### T5 — UI 驗收主要停留在函式輸出

**`src/lib/supplement.test.ts:192–228、265–310、362–380` / Medium**

- B4 沒有渲染 App，也未驗證與 F 橫幅並存。
- B6 只測 `loadSupplement()` 與純函式，未測兩檔完成順序及 App 的實際畫面。
- B7 沒有驗證導覽列和區塊實際顯示數字。
- B9 只比較 key 字串，不能證明展開狀態或沒有 React duplicate-key 警告；這點 r5 已誠實列為待補。
- 沒有頁面保持開啟跨越 3 天門檻的測試，因此未攔下 R4。

**建議修法：** 補元件／瀏覽器測試，使用非空 supersedes、非空恢復 additions 與可控制時鐘，驗證最終畫面及互動身分。

### T6 — 入口污染測試不足

**`src/lib/supplement.test.ts:384–400`；`scripts/test_supplement_scraper.py:625–631` / High**

- 前端只覆蓋少數欄位缺失／型別反例，沒有 R1、R2 的無效 base、未來恢復日期、非法案件編號及編號對應錯誤。
- 前檔損壞只測無法解析 JSON，沒有「JSON 可解析但 schema／逐筆資料不合法」。

**建議修法：** 每個反例都經正式 loader 入口，並帶有足以隱藏缺藥的非空資料，斷言原可見缺藥仍保留、主畫面不崩潰。

## 3. Dependency audit

以 lockfile 實際版本為準：Vite **8.0.8**、Vitest **3.2.7**、React／React DOM **19.2.5**。不能僅依 `package.json` 的版本下限判斷漏洞。

| 位置／嚴重度 | 問題描述 | 建議修法 |
|---|---|---|
| `package-lock.json:9047–9048` / **Medium** | Vite 8.0.8 落在 Windows 路徑繞過漏洞的受影響範圍；條件包含對網路暴露 dev server。這是開發環境風險，不能推論 GitHub Pages 靜態站可被利用。[官方公告](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff) | 升級到涵蓋目前安全修補的受支援版本，更新 lockfile 並重驗 build／PWA；不要只修到已知單一公告的最低版本。 |
| `package-lock.json:9254、9327` / **Low** | Vitest／mocker 3.2.7 落在 GHSA-82fw-gwwq-j7x9 範圍；但利用主要涉及公開 mocker／interceptor plugin 的 dev-server WebSocket，本 repo 未見該設定，不能宣稱目前可遠端利用。[官方公告](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9) | 規劃升級至已修補版本並確認 Vite 相容性；保留既有斷言強度。 |
| `scripts/register_supplement_task.ps1:3–5`；`scripts/update_supplement.py:20` / **Medium** | requests 無版本約束或 lock；排程 venv 與手動 `uv run --with requests` 也可能使用不同環境。無法由 repo 重建實際依賴版本，亦無法對排程環境完成漏洞判定。 | 用 `uv` 管理版本與 lock，讓排程、手動執行及測試使用同一組依賴。 |
| `.github/workflows/update_data.yml:31–34`；`scripts/fetch_fda_data.py:12–19` / **Low** | 既有 CI 安裝 `pandas`，正式 ETL 未使用；增加不必要安裝量及相依面。此為基線既有問題。 | 移除不使用的 pandas；將實際 Python 依賴納入版本管理。 |

授權方面，lockfile 未見足以直接判定衝突的項目；`lightningcss` 為 MPL-2.0、`caniuse-lite` 為 CC-BY-4.0，不能僅因授權名稱不同就列為違規。此輪未完成所有套件原始授權文件的法律稽核。

Requests 官方目前列有 `<2.33.0` 的特定工具函式漏洞，但公告明示一般 Requests 使用不受影響；本程式未呼叫該工具函式，因此不列為已確認可利用漏洞。[官方公告](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2)

## 4. 規格符合度稽核

下表沿用 R／T 編號避免重複描述；列出的嚴重度及修法對應前述發現。

### D1–D12

| 條款 | 實作位置 | 核對結果／修法 |
|---|---|---|
| D1 | `scripts/supplement_scraper.py:711–732` | 未發現補抓寫入主檔；符合資料隔離方向。 |
| D2 | `src/lib/supplement.ts:266–293`；`src/App.tsx:85–91` | 從原始主檔計算，再交既有清洗；未發現增量重複套用。 |
| D3 | `scripts/register_supplement_task.ps1:19–28` | 固定本機排程符合；C2 尚未完成，依規格不作上線阻擋。 |
| D4 | `scripts/supplement_scraper.py:640–686` | **High，R3：**「可用前檔」被弱化成容器型別檢查。補完整前檔驗證。 |
| D5 | `scripts/supplement_scraper.py:549–612` | 核心差集方向未發現違反；可信度仍受 R5–R7 的輸入守門缺陷影響。 |
| D6 | `scripts/supplement_scraper.py:526–546`；`src/lib/supplement.ts:207–250` | 比較單位、重數及 s2 隱藏含證號的方向符合；兩端明列空白集合未發現不一致。 |
| D7 | `scripts/supplement_scraper.py:373–385` | **Medium，R5：**「同日內容完全相同」被弱化為正規化相同。改用精確內容判定。 |
| D8 | `scripts/supplement_scraper.py:504–521` | 兩輪／整次重試架構存在；**Medium，T3：**驗收未充分證明只用重試觀測。 |
| D9 | `scripts/supplement_scraper.py:575–580` | 熔斷公式與超過才阻擋符合；沒有要求放寬。 |
| D10 | `src/lib/supplement.ts:175–179`；`src/App.tsx:85–88` | **High，R1、R4：**未知基準仍可信，且頁面時間推進後不撤銷信任。 |
| D11 | `scripts/update_supplement.py:64–117`；`scripts/test_update_supplement.py:17–87` | error 快照發布、重試及禁止 force 的流程存在；**High，T1：**發布內容與 base 保存未被所宣稱測試證實。 |
| D12 | `scripts/supplement_scraper.py:12–25` | 解析使用標準庫及 requests，未增加 bs4；依賴重現性問題見 dependency audit。 |

### §6 契約與失敗行為

| 條款／嚴重度 | 實作位置 | 未做到或做弱之處／建議修法 |
|---|---|---|
| §6.1、D10 / **High** | `src/lib/supplement.ts:108–128、175–179` | 接受成功狀態卻無合法 base 的快照；建立狀態與欄位之間的相依契約，未知基準禁止隱藏。 |
| §6.2 / **High** | `src/lib/supplement.ts:91–105` | 日期、證號、案件編號及衍生編號未完整驗證；依 R2 修復。 |
| §6.2、D7(d) / **Medium** | `scripts/supplement_scraper.py:184–189、367–385` | 原文保留與同日完全一致被弱化；依 R5 修復。 |
| §6.3「尚無資料」 / **Medium** | `scripts/supplement_scraper.py:295–313` | 只看節點存在，不看空狀態文字；依 R6 修復。 |
| §6.3 非 200／非預期跳轉 / **Medium** | `scripts/supplement_scraper.py:436–448` | 錯誤條件未完整觸發；依 R7 修復。 |
| §6.3 前檔 schema 不符 / **High** | `scripts/supplement_scraper.py:649–673` | 可解析但損壞的前檔仍可沿用；依 R3 修復。 |
| §6.3 按類別過期警示 / **High** | `src/App.tsx:85–88` | 只在輸入物件改變時重算，無法保證開啟中的頁面超過三天後警示；依 R4 修復。 |

`excluded_no_license` 確實由管線產生並存在於目前 JSON；它未顯示於 UI，但規格只要求記錄，**不將此列為「欄位無作用」問題**。

### A1–A12

| 條款 | 檔案:行號／嚴重度 | 差距與建議 |
|---|---|---|
| A1 | `scripts/test_supplement_scraper.py:225–238、697–709` / **High** | 完整原文斷言不足；完整流程只有改日期。補完整原文與同日修訂流程。 |
| A2 | 同檔 `356–413` / **Medium** | 缺各反例沿用前檔斷言；跨組只驗解析。依 T3 補強。 |
| A3 | 同檔 `419–435` / **Medium** | 有驗另一類成功時間前進，但沒有比較前檔全部結果欄位。補 base、success_run_id、supersedes 等完整沿用斷言。 |
| A4 | 同檔 `273–289` / **High** | 多為 validator 單點測試，缺第四筆失敗及真實 HTTP 邊界。依 T2 補強。 |
| A5 | 同檔 `443–460`；scraper `295` / **Medium** | 缺空狀態節點文字改變反例，未攔下 R6。 |
| A6 | 同檔 `466–486、634–640` / **Medium** | 共用案例跳過正式分類流程；主檔名稱只測零個換行，未測兩個。補流程級反例及完整期望內容。 |
| A7 | 同檔 `241–264` / **Low** | 有 COSOPIN、滅必治及無英文案例；未完整覆蓋列明的全形引號、`/`、`&` 組合。補明確輸入輸出。 |
| A8 | 同檔 `520–528` / **Low** | 有主流程拒絕與逐位元不變，但未驗證 CLI 實際 exit 1。補入口測試。 |
| A9 | 同檔 `531–559` / **Medium** | 兩種原子寫入失敗有涵蓋；成功快照只驗部分頂層欄位，非完整 schema。補完整輸出契約驗證。 |
| A10 | 同檔 `565–631` / **Medium** | 有基本生命週期，但沒有 Python 產出非空 s2 沿用快照再接 TS 清洗的跨端證據。補共用跨次輸出 fixture。 |
| A11 | `scripts/test_update_supplement.py:17–124` / **High** | 發布檔案內容、base 與排程 XML 未被驗證。依 T1 修復。 |
| A12 | `scripts/test_supplement_scraper.py:655–683` / **Medium** | 重試來源斷言不具區別力、缺跨類移動及前檔完整沿用。依 T3 修復。 |

### B1–B9

| 條款 | 檔案:行號／嚴重度 | 差距與建議 |
|---|---|---|
| B1 | `src/lib/supplement.test.ts:102–120` / **High** | 缺共用案例清洗後集合、指紋及補抓輸入不變性。依 T4 補強。 |
| B2 | 同檔 `125–155` | 有非空 s2 error 反例及完整清洗後身分集合，未發現所列情境的明顯缺漏。 |
| B3 | 同檔 `157–187` / **Medium** | 改日期有驗文字；同日只驗 ID，徽章只驗 URL helper。補實際內容及徽章渲染。 |
| B4 | 同檔 `192–228` / **Medium** | 只驗 warnings 字串，未驗渲染及 F 並存。依 T5 補強。 |
| B5 | 同檔 `231–260` / **Medium** | 函式時間邊界有測；未涵蓋 App 跨時間門檻及真正缺欄入口。補 R4、T6 反例。 |
| B6 | 同檔 `265–294` / **Medium** | 有降級集合比對，但未驗兩檔不同完成順序及 App 畫面。 |
| B7 | 同檔 `297–310` / **Medium** | 驗清洗函式計數，未驗導覽與區塊計數。 |
| B8 | 同檔 `314–358` / **High** | 四個正常型別反例存在，但未知／損壞 base 未測，D10 實際仍可繞過。依 R1 補強。 |
| B9 | 同檔 `362–380` / **Medium** | key 函式測試存在；互動與 console 驗收待補，r5 §9 已承認，不能計為完成。 |

### C1–C4

| 條款 | 檔案:行號／嚴重度 | 差距與建議 |
|---|---|---|
| C1 | `.ai-review/plan-supplement.md:261–262`；`public/data/supply_supplement.json:6–114` / **High** | Repo 有彙總結果及差異檔，未找到可追溯的三類逐列獨立核對產物。237 筆內容相符的敘述不能替代單位、重數、目標列核對。補附獨立核對結果、起訖時間及基準；無法據現有證據認定 C1 完成。 |
| C2 | `.ai-review/plan-supplement.md:263`；`.github/workflows/` / **Low** | 未執行，且目前沒有專用 dsms 探測 workflow。補只讀探測及紀錄；依 D3 明確不阻擋上線、不改排程位置。 |
| C3 | `.ai-review/plan-supplement.md:243、264` / **Medium** | 使用者本人核對待辦；另「舊公告 addition」已因 r5 空證號排除決策而無法照原條款完成。應更新驗收案例為核對排除紀錄，再完成實際 additions／supersedes 人工確認；不能為滿足舊條款重新納入排除資料。 |
| C4 | `SMOKE_TEST.md:21–22、30–32`；`public/data/supply_supplement.json:112` / **Medium** | 離線三項明確未測。#5／#6 的紀錄只寫 s2 error，未留下非空恢復 addition、同日兩版的測試資料與身分證據；目前提交的 s2 additions 為空，不能由此重建驗收。補可重現的具體案例及瀏覽器結果。 |

**合併門檻：先修復 R1–R4 的漏報／降級缺陷，補上對應入口反例與真正的發布內容斷言，再重新覆審。C2 保持非阻擋；其餘未完成驗收應如實保留，不以測試總數或既有「全過」紀錄代替。**

Codex session ID: 01a176cf-fabb-70a2-8e4c-6a7949fabfc5
Resume in Codex: codex resume 01a176cf-fabb-70a2-8e4c-6a7949fabfc5
