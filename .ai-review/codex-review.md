# Codex 獨立覆審原始報告（未經修飾）

- **審查日期**：2026-07-21
- **Codex 版本**：OpenAI Codex（mcp__codex，預設模型）；thread `019f821b-1d96-7083-a483-392dbcee796e`
- **審查範圍**：整個 repository（重點 src/App.tsx、src/PwaBanners.tsx、scripts/fetch_fda_data.py、vite.config.ts、.github/workflows/*.yml、package.json）
- **Commit hash**：48289401b636363b70f33d6439531b066684d8a0
- **模式**：read-only（Codex 未修改任何檔案）

> 以下為 Codex 原始輸出，逐項意見未經 Claude 刪改，僅供稽核。判定請見 `verdict.md`。

---

## 覆審結論

共識別：

- Critical：1 項
- High：5 項
- Medium：7 項
- Low：5 項

最高風險不是 XSS，而是 ETL fail-open：任一 TFDA API 失敗時，workflow 仍可能把空資料發布為「目前沒有短缺品項」。其次是「缺藥天數」語意錯誤、PWA 可能持續顯示舊 JSON，以及核心日期比較缺乏嚴格解析。

本次全程唯讀，未修改檔案。`npm audit` 因環境無法連線 npm registry，不能宣稱目前「零已知漏洞」。

# 1. Code review

### CR-01：API 失敗會被當成空資料發布

scripts/fetch_fda_data.py:12、update_data.yml:29 / **Critical** / `fetch_data()` 捕捉所有例外後回傳 `[]`，`main()` 仍覆寫 JSON、更新 `last_updated`，workflow 也會成功並 commit。若 105 抓取失敗，前端會顯示「無替代 0」；三個端點都失敗時，則可能發布近乎空白的儀表板。這正是威脅模型中最高權重的資料入口污染。 / **建議修法：** 改為 fail-closed；任一必要端點連線、HTTP、JSON 或驗證失敗即以非零狀態結束，不寫正式檔。先寫暫存檔，全部端點驗證成功後才原子替換。加上最小筆數、相對前次筆數劇烈下降等 sanity checks。這完全相容於 GitHub Actions + 靜態 JSON 架構，不需要後端。

### CR-02：API 回傳沒有結構與欄位驗證

scripts/fetch_fda_data.py:14 / **High** / `response.json()` 的任何 JSON 都直接寫入。HTML 錯誤頁通常會解析失敗，但合法 JSON 錯誤物件、欄位改名、欄位型別變更、截斷資料、TFDA sentinel row 都不會被阻擋。目前 105 實際包含一筆 `編號="沒有資料"`、其他欄位為 null；只是剛好被前端 identity filter 排除。 / **建議修法：** 在 ETL 驗證最外層必須是 list，每筆只接受必要欄位，並檢查 `公告更新時間`、`中文品名`、`許可證字號`、`供應狀態` 型別。明確辨識「沒有資料」sentinel，與「抓取失敗」分開。驗證失敗應中止 workflow 並保留上一版 JSON。

### CR-03：「缺藥 N 天」其實是距公告更新日的天數

src/App.tsx:33、src/App.tsx:184、src/App.tsx:503 / **High** / `_days` 使用 `公告更新時間` 與今天相減，但 UI 標成「缺藥 N 天」。公告更新時間不是短缺開始日；公告也可能因恢復預估、供應狀況修訂而更新。這會直接誤導短缺持續時間及 urgency 分級。 / **建議修法：** 若沒有可信的短缺開始欄位，改標示「公告距今 N 天」或「最後更新 N 天前」，且不要用它表示缺藥持續時間。若要顯示真正缺藥天數，須從可信欄位或可驗證事件序列取得起始日，不能以公告更新日替代。

### CR-04：殭屍清除使用非標準日期解析，異常日期會靜默失效

src/App.tsx:153 / **High** / `new Date("YYYY/MM/DD")` 不屬於 ECMAScript 保證一致的日期格式。若解析為 `NaN`，可能污染 `resolvedDates`：第一筆無效解除日期會被存入 Map，後續有效日期也無法以 `dTime > NaN` 取代；shortage filter 則會默默保留殭屍品項。排序也使用相同解析方式。 / **建議修法：** 建立單一嚴格 `parseTfdaDate()`，用 regex 解析 `YYYY/MM/DD` 後，以數值建構日期並驗證年月日沒有 rollover。無效日期應由 ETL 阻擋，不應在前端被當成可用資料。供應狀態內的民國日期則應另用明確 ROC parser；不要和公告欄位的西元格式共用隱式解析。

### CR-05：PWA 的 StaleWhileRevalidate 會讓當次畫面繼續顯示舊資料

vite.config.ts:29、src/PwaBanners.tsx:58 / **High** / JSON 使用 `StaleWhileRevalidate`：已快取時先把舊 JSON 交給 React，再於背景更新 cache，但 React 不會因 cache 更新自動重新 fetch。`needRefresh` 代表 service worker/app shell 有新版本，不代表 runtime-cached JSON 已更新；只變動 JSON 時甚至不一定出現「資料已更新」banner。臨床使用者可能直到下一次重載才看到新資料。 / **建議修法：** 對 JSON 改用 `NetworkFirst`，網路失敗才退回 cache；或在背景更新完成後用 Workbox broadcast/message 通知 React 重新 fetch。更新提示應比較 JSON 的 `last_updated`，不能用 `needRefresh` 代替資料版本。此作法完全相容純靜態 PWA。

### CR-06：repo 內資料已明顯超過每週更新週期

public/data/supply_status_latest.json:2、update_data.yml:4 / **High** / 本次檢出的 `last_updated` 為 `2026-05-22 06:58:07`，系統日期為 2026-07-21，已約 60 天；與每週五排程不符。這只能證明目前 checkout 的資料過期，不能直接證明 live Pages 相同，但 repo 缺少任何 freshness gate。 / **建議修法：** workflow 在 commit/deploy 前檢查資料年齡，例如超過 8–10 天即失敗並發出通知；前端也應以醒目 banner 顯示「資料已超過預定更新週期」。這是靜態架構可直接實作的防線。

### CR-07：替代藥 regex 會把非藥名內容標成替代建議

src/App.tsx:41、src/App.tsx:508 / **Medium** / 現有 JSON 的 266 筆 104 資料中只有 10 筆命中；多個結果是「與缺藥品項成分不盡相似」、「替代」、「(詳述如下)」或圖卡 URL，而不是替代藥名。這些內容會被放入 💡 tag，視覺上像經解析確認的替代品。 / **建議修法：** 單純收緊 regex 會與已聲明的高召回率取捨衝突，因此不建議只靠縮窄 pattern。相容作法是保留寬鬆候選擷取，但增加 confidence/provenance：只有符合藥名、許可證或 `◎` 清單結構者顯示「替代品候選」，其餘顯示「公告含替代資訊，請展開查看」，不要把低信心片段直接標成藥名。

### CR-08：重複事件沒有去重，會膨脹卡片及統計

src/App.tsx:180、src/App.tsx:93、src/App.tsx:475 / **Medium** / `all` 直接串接資料集，統計按 row 累加。現有 106 中「衛署菌疫輸字第000935號／2024-08-20」存在完全重複事件；會顯示兩張相同卡片並使解除數與圖表多計一次。同月份同證號亦會產生重複 React key。 / **建議修法：** ETL 先依「資料集＋許可證字號＋公告日期＋正規化供應狀態」去除完全重複 row。不可只依許可證去重，否則會合併不同短缺 episode，與現有事件歷史需求衝突。React key 可加入公告日期、編號及內容 fingerprint。

### CR-09：「最新十筆」受目前排序模式影響，且完全忽略篩選與搜尋

src/App.tsx:203 / **Medium** / 程式先依 `sortMode` 排序，再 `slice(0,10)`。因此若排序為名稱或缺藥最久，「顯示最新十筆」並不會顯示最新資料。同時該分支略過搜尋、狀態、年月條件；搜尋框仍可輸入但不生效。 / **建議修法：** 明確定義功能語意。若名稱就是「最新十筆」，應固定依嚴格解析後的公告日期排序再切片；搜尋與篩選可在切片前套用，或切換時清空並停用所有不生效的控制項。

### CR-10：前端只確認 JSON 可解析，沒有 HTTP 與 runtime schema 防線

src/App.tsx:138 / **Medium** / 沒有檢查 `res.ok`，也直接把 `json` cast-like 地放入 `SupplyData` state。合法但錯誤的 JSON 會在後續存取 `data.datasets[...]` 時造成未捕捉例外或錯誤統計。 / **建議修法：** 先檢查 `res.ok`，再用 type guard/schema 驗證 `last_updated`、`datasets` 和三個必要 array。前端驗證是 ETL fail-closed 之外的第二道防線，不是取代 ETL。

### CR-11：ETL 時間戳缺少時區

scripts/fetch_fda_data.py:24、src/App.tsx:270 / **Medium** / GitHub-hosted Ubuntu runner 通常使用 UTC，但 ETL 寫入沒有 offset 的 naive datetime；前端直接當文字顯示，台灣使用者可能看到少 8 小時的更新時間。 / **建議修法：** 儲存 ISO 8601 UTC，例如 `2026-07-21T06:00:00Z`，前端以 `Intl.DateTimeFormat('zh-TW', { timeZone: 'Asia/Taipei' })` 顯示；或 ETL 明確產生 `+08:00` 時間。

### CR-12：CRLF replacement 寫成匹配字面反斜線

src/App.tsx:47、src/App.tsx:529 / **Low** / JSON parse 後換行是實際 `\r\n` 字元，但 `/\\r\\n/g` 匹配的是字面 `\r\n` 四個字符。因此 replacement 實際不會生效；恢復時間 regex 也可能跨越換行抓入下一段。詳細內容目前由 CSS `white-space: pre-line` 處理，所以渲染影響有限。 / **建議修法：** 使用 `/\r?\n/g`；萃取前可統一換行為 `\n`，並以編號段落或句號為邊界。

### CR-13：統計宣稱「項數」與「件數」，但事件模型沒有明確定義

src/App.tsx:76、src/App.tsx:361 / **Low** / `uniqueDrugCount` 依許可證或品名去重，但圖表與「通報件數」按 row 計算；完全重複 row、同證號多 episode 和目前篩選條件都會改變數字。演算法本身可成立，但缺乏事件單位定義，容易被誤讀為目前受影響品項。 / **建議修法：** 文件與 UI 明確區分「唯一許可證數」「公告事件數」「目前未解除事件數」，並在 ETL 產生穩定 event ID。

### CR-14：型別在統計與 Section 邊界被 `any` 繞過

src/App.tsx:83、src/App.tsx:329、src/App.tsx:422 / **Low** / `Record<string, any>`、`as any` 和 `Section(...: any)` 使錯誤 theme、sort mode 或資料形狀無法由 TypeScript 阻擋。 / **建議修法：** 定義 `SortMode`、`ChartBucket`、`ChartDatum`、`SectionProps` interfaces；select handler 先驗證 value 再設 state。

### 安全性補充

未發現 `dangerouslySetInnerHTML` 或其他可繞過 React escaping 的渲染路徑。TFDA 文字在 JSX text node 中輸出，依目前威脅模型，不應把理論性 XSS 列為高風險。

# 2. Test gap analysis

目前 package.json:6 沒有 `test` script，repository 也沒有測試檔。建議依以下順序補強。

### TG-01：ETL fail-closed 與原檔保留

scripts/fetch_fda_data.py:12 / **Critical** / 缺少 timeout、HTTP 500、TLS、JSON decode、單一端點失敗、全部端點失敗的測試。 / **建議修法：** mock `requests.get`，確認任何必要端點失敗時程式非零退出、正式 JSON 不變、workflow 不進入 commit。

### TG-02：schema、sentinel 與筆數異常

scripts/fetch_fda_data.py:29 / **High** / 缺少合法 list、錯誤 object、缺欄、null、錯誤型別、空 list、「沒有資料」sentinel、資料量驟降測試。 / **建議修法：** 以 fixture 驗證 sentinel 可被正確解讀為「官方回覆無資料」，但任意空陣列或結構錯誤不能被誤判成相同狀態。

### TG-03：殭屍事件與日期順序矩陣

src/App.tsx:153 / **High** / 缺少 shortage→resolved、resolved→新 shortage、同日解除、同證號多 episode、無證號、前後空白、無效日期等測試。 / **建議修法：** 將資料清洗抽成 pure function，測試「解除日 >= shortage 日才清除該事件」，並驗證新一輪 shortage 不會被舊解除資料刪除。

### TG-04：缺藥天數與日期邊界

src/App.tsx:33 / **High** / 缺少今天、未來日期、月底、閏年、無效日期、UTC/Taipei 跨日測試；更缺少欄位語意測試。 / **建議修法：** 注入固定 clock/timezone，測試純日期差；若資料只有公告更新日，測試 UI 必須顯示「公告距今」而不是「缺藥」。

### TG-05：PWA 資料更新與離線退回

vite.config.ts:26、src/PwaBanners.tsx:4 / **High** / 缺少「已有舊 cache、伺服器已有新 JSON」「完全離線」「cache 過期」「只有 JSON 更新、service worker 不變」情境。 / **建議修法：** 至少做 Playwright/PWA integration test，確認線上優先顯示最新 `last_updated`，離線才使用 cache，且畫面明確標示離線資料時間。

### TG-06：regex 高召回率與低信心顯示

src/App.tsx:41 / **Medium** / 缺少 TFDA 真實公告 corpus 的 regression tests。 / **建議修法：** 保存去識別化的真實文字 fixture，分成「明確藥名」「泛稱替代」「詳述如下」「圖卡 URL」「無替代」「多段落」。測試重點不是強迫 regex 變嚴，而是避免低信心片段被 UI 當成已確認藥名。

### TG-07：去重與統計不變量

src/App.tsx:76 / **Medium** / 缺少完全重複 row、同證號不同 episode、缺證號同品名、同月重複 key，以及統計合計數測試。 / **建議修法：** 驗證完全重複事件只計一次，但不同日期或不同狀態的合法 episode 必須保留。

### TG-08：排序、篩選及最新十筆組合

src/App.tsx:199 / **Medium** / 缺少搜尋 × status × year × month × sort × latest-ten 的組合測試。 / **建議修法：** 優先覆蓋 `latestTen + name sort`、`latestTen + longest sort`、搜尋中切換 latest-ten、無效月份及同日穩定排序。

### TG-09：前端錯誤資料與過期資料提示

src/App.tsx:138 / **Medium** / 目前只有 fetch rejection 測試需求，沒有 HTTP 404、合法錯誤 JSON、缺 datasets、資料超過更新週期等情境。 / **建議修法：** 驗證這些情境顯示可理解的錯誤或過期警示，不應 render 成零筆正常資料。

# 3. Dependency audit

### DA-01：無法完成線上 vulnerability audit

package-lock.json:1 / **Medium** / `npm audit --package-lock-only` 因受限網路無法連線 `registry.npmjs.org`。因此本報告不能確認 2026-07-21 當下是否有 npm advisory。 / **建議修法：** 在 GitHub Actions 或 Dependabot/Renovate 執行 lockfile vulnerability scan，至少對 production 與完整 dependency tree 各跑一次；Critical/High advisory 應阻擋 deploy。

### DA-02：Python dependency 未固定，且安裝不必要的 pandas

update_data.yml:24 / **Medium** / 每週以寫入 repository 的 token 執行最新 `requests`、`pandas` 和升級後的 pip；`pandas` 未被 ETL 使用。這增加供應鏈面積與不可重現性。 / **建議修法：** 移除 pandas；用 requirements/lockfile 固定 requests 與 transitive versions，理想上使用 hash 驗證。這不影響零後端架構。

### DA-03：有已棄用且自述含已知漏洞的 transitive `glob`

package-lock.json:4984、package-lock.json:8537 / **Low** / `glob@11.1.0` 被標示 deprecated，訊息明確指出舊版本含公開漏洞；由 `workbox-build@7.4.1` 引入，屬 build-time dev dependency，未直接進入瀏覽器 runtime，因此依威脅模型下修為 Low。 / **建議修法：** 優先升級 `vite-plugin-pwa`/Workbox 至採用受支援 glob 的版本。不要未經相容性測試直接 override major version。

### DA-04：`source-map@0.8.0-beta.0` 已棄用

package-lock.json:7525、package-lock.json:8561 / **Low** / Workbox build chain 使用已棄用的 beta package。它是 build-time dependency，沒有直接臨床資料邏輯影響。 / **建議修法：** 隨 Workbox/vite-plugin-pwa 升級移除；不建議單獨強制 override。

### DA-05：deploy 沒有使用 lockfile 的嚴格安裝模式

deploy.yml:40 / **Low** / 使用 `npm install` 而非 `npm ci`。雖然已有 lockfile，但 CI 可重現性與 lock/package 不一致的失敗保證較弱。 / **建議修法：** 改用 `npm ci`，並在 build 前執行 lint、資料 schema/freshness checks。

### DA-06：GitHub Actions 只固定 major tag

update_data.yml:16、deploy.yml:32 / **Low** / `actions/checkout@v4`、`setup-python@v5` 等 tag 可移動；其中 update workflow 具有 `contents: write`，供應鏈遭入侵時可污染資料與 repository。 / **建議修法：** 將 Actions 固定到完整 commit SHA，保留註解標示對應版本，並使用 Dependabot 更新。

### 授權檢查摘要

直接依賴 React、React DOM、Recharts、Vite、vite-plugin-pwa 為 MIT，TypeScript 為 Apache-2.0，未見明顯商用或再散布衝突。Transitive tree 主要為 MIT、Apache-2.0、BSD、ISC、MPL-2.0；`caniuse-lite` 為 CC-BY-4.0。兩個 `@emnapi/*` lock entries 沒有 license metadata，這不等於無授權，但若要產生正式 SBOM/NOTICE，應再由 registry/package tarball 驗證。
