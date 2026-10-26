# 覆審判定（增量 S：dsms 公告頁補抓）

> 對象：`codex-review-supplement.md`（Codex，2026-10-26，commit `34054ca`）。判定者：Claude。
> 每項都回到檔案原處驗證；行號以 `34054ca` 為準。

## 判定表

| # | 項目 | 嚴重度 | 判定 | 理由 |
|---|------|--------|------|------|
| R1 | 缺失／無效 base 反而允許隱藏 | High | **接受** | `src/lib/supplement.ts` `mainOlderThanBase()`：`parseLastUpdated(base.last_updated)` 為 null 時 `return false`，被當成「版本沒問題」；`isCategory()` 對 `base` 只驗是 object。`base:{last_updated:123}` 會在 `parseLastUpdated` 的 `s.trim()` 拋例外，整頁 useMemo 崩潰。`scripts/supplement_scraper.py` `load_main()` 也沒驗頂層 `last_updated`，主檔缺欄時會寫出 `base.last_updated: null` 的「成功」快照。違反 D10「版本相容」與 fail-closed 原則 |
| R2 | 前端 additions 驗證弱於 §6.2 | High→**Medium** | **部分接受** | 問題屬實：`isAddition()` 用 `parseTfdaDate`（允許 `YYYY/M`、無未來日期上限）、證號只驗非空、未驗 `編號 === "dsms-"+_案件編號`。但前提是補抓檔內容錯誤，而產出端 `validate_detail()` 已依 §6.2 驗證，所以需要「產出端 bug 或 repo 檔案被竄改」才會觸發，降為 Medium。修法照 Codex：前端補嚴格日期＋未來上限、證號 pattern、編號對應、supersedes 日期格式。這是縱深防禦，不改 zombie 規則 |
| R3 | 損壞前檔被沿用，連帶整份補抓檔被拒 | High→**Medium** | **部分接受** | `scripts/supplement_scraper.py` `_valid_previous_category()` 只驗 list／str／dict 型別，不驗 additions 逐筆內容；沿用 `[null]` 會被前端 `isSupplementData` 整份拒收，s3/s4 的新缺藥一起消失。屬實且破壞 D4 的故障隔離。但結果是**整頁亮紅「無法載入補抓資料」**，不是靜默漏報，故降為 Medium。修法：沿用前逐筆驗證（與輸出同一套契約），寫檔前再驗一次輸出 |
| R4 | 開著的頁面不會隨時間撤銷信任 | High | **接受** | `src/App.tsx`：`applySupplement(data, supplement)` 的 `now` 只在 `[data, supplement]` 變動時重算。藥局工作站分頁常駐數天是常態（recall-dashboard 今天剛修過同型 bug：新鮮度只在載入時判一次）。過了 3 天門檻，舊公告仍被隱藏、紅色警示不出現＝漏報風險 |
| R5 | 同日多列比較與原文保留變弱 | Medium | **接受** | `latest_history()` 以 `norm(text)` 判斷同日多列一致，規格 D7(d)／§6.2 寫「內容完全相同」；`display_text()` 對每一行 `rstrip()`，規格寫「只去除頭尾空白」；`text_of()` 忽略 `<br>`（現行頁面在 `<br/>` 前有原始換行所以正常，但只靠 `<br>` 換行時替代藥清單會黏在一起）。修法：同日比較改用 `display_text` 後精確比較；`<br>` 轉換行並合併「換行＋`<br>`」造成的重複換行；只去整段頭尾空白 |
| R6 | 空集合只認 element id | Medium | **接受** | `parse_list_page()`：`empty = find_by_id(grid, ..._lbEmpty) is not None`，未檢查文字。若該節點變成「系統維護中」，L＝∅、supersedes＝全部 O；主檔 ≤3 筆的類別可通過熔斷。修法：同時要求文字為「尚無資料」 |
| R7 | HTTP 狀態與來源檢查不足 | Medium→**Low** | **部分接受** | `DsmsClient._request()` 用 `raise_for_status()`（2xx 皆過）且未核對 scheme／host。屬實但要觸發需 dsms 回非 200 的 2xx 或跳轉到別的主機且頁面身分（標題、grid id）仍通過，機率低，降為 Low。修法便宜：要求 200、https、`dsms.fda.gov.tw` |
| R8 | `main_unit()`／`record_unit()` 重複組裝單位 | Low | **接受** | 兩者各自組「品名鍵＋日期（＋證號＋指紋）」，任一端改動會漂移。抽共用組裝函式 |
| T1 | 包裝測試只驗 commit 訊息 | High→**Medium** | **部分接受** | `FakeRunner` 的 `local/remote` 只存訊息，不能證明發布的是 error 快照或 base 未被改寫。屬實；但包裝程式本身從不讀寫 JSON（只 `git add/commit/push` 指定路徑），base 被改寫的路徑不存在，風險在「測試宣稱的性質比實際驗的強」，降為 Medium。修法：測試改為對真實暫存 git repo（`git init` + bare remote）跑，比對遠端檔案內容。排程設定測試改為去掉註解後再比對旗標（無法在測試讀實機排程 XML，改在 SMOKE_TEST 列「註冊後匯出 XML 核對」） |
| T2 | 「保留所有替代藥」未驗完整文字；A4 第四筆壞未測；真正 DsmsClient 未測 | High | **接受** | `test_a1_full_text_keeps_every_alternative` 只驗 6 行 `◎` 與最後一行開頭；規格 A4 明列的「前 3 筆正常、第 4 筆壞 → 整類 error、last_success_at 不前進」**沒有測試**（規格符合度缺口）；`DsmsClient` 的跳轉／狀態檢查沒有測試。補：易安穩完整原文逐字、A4 第四筆壞的流程級測試、以假 session 測 `DsmsClient` |
| T3 | A2／A12 只驗 helper | Medium | **接受** | A2 反例只斷言 `scan()` 拋錯，未驗沿用前檔；A12(c) 只比筆數；**規格 A12(b)「移類」沒有測試**（規格符合度缺口）；A12(d) 未經 orchestration。補強為流程級、各輪內容可區別 |
| T4 | 共用 fixture 只驗清洗前序列 | High→**Medium** | **部分接受** | 規格 B1 明寫「分別斷言套用後清洗前與經 `cleanSupplyData` 後兩個集合，逐列寫明保留哪一筆（含指紋）」，實作只驗清洗前 `編號` 序列＝**規格符合度缺口**，接受。Python A6 走 `compute_case()` 而非 `process_category()` 屬實，但 A6 規格是「差異計算」的純函式性質，流程級覆蓋由其他整合測試補（同日修訂整合測試確實缺，併入 T2）。嚴重度 Medium |
| T5 | UI 驗收停在函式輸出 | Medium | **部分接受** | 規格 B4 寫「斷言實際渲染的文字」，實作只驗 warnings 字串＝規格符合度缺口。修法不引入 jsdom／testing-library（新依賴）：把橫幅抽成純元件，用既有 `react-dom/server` 的 `renderToStaticMarkup` 驗渲染文字與 F 並存。B9 互動與 App 兩檔完成順序維持 r5 §9 已承認的待補，改列 SMOKE_TEST |
| T6 | 入口污染測試不足 | High→**Medium** | **部分接受** | 隨 R1／R2／R3 修補補上對應反例（無效 base、未來恢復日期、非法案件編號、編號不對應、可解析但逐筆非法的前檔），並經正式 loader 入口。嚴重度隨 R2／R3 降為 Medium |
| D-1 | Vite 8.0.8 漏洞 | Medium | **部分接受** | `npm audit` 實際列出 17 項（2 critical：vitest、tinypool；9 high 含 vite、postcss），比 Codex 列的多。全部是 dev／build 工具鏈，執行面是本機 dev server 與 CI build，不進入 Pages 靜態產物；且 `package.json`／lockfile 本分支**未改動**，屬 main 既有問題。另開 `chore(deps)` 處理，不阻擋本增量 |
| D-2 | Vitest 3.2.7 漏洞 | Low | **部分接受** | 同 D-1，併入另案升級 |
| D-3 | requests 未鎖版本 | Medium→**Low** | **部分接受** | 屬實：排程 venv 與 `uv run --with requests` 可能不同版本。降為 Low（requests 用法單純）。修法：`register_supplement_task.ps1` 與 README 指定 `requests==` 固定版本，與 CI 的 scraper 一致 |
| D-4 | CI 安裝未使用的 pandas | Low | **部分接受** | 屬實（`update_data.yml` 安裝 pandas、`fetch_fda_data.py` 未 import），但屬 main 既有、與本增量無關 → 併入 D-1 另案 |
| S-D4 | 規格 D4 可用前檔被弱化 | High→Medium | 部分接受 | 同 R3 |
| S-D7 | 規格 D7(d) 同日內容完全相同 | Medium | 接受 | 同 R5 |
| S-D8 | 規格 D8 只用重試觀測未被證明 | Medium | 接受 | 同 T3 |
| S-D10 | 規格 D10 未知 base、時間推進 | High | 接受 | 同 R1、R4 |
| S-D11 | 規格 D11 發布內容未被測試證實 | High→Medium | 部分接受 | 同 T1 |
| S-6.1 | 成功狀態卻無合法 base | High | 接受 | 同 R1 |
| S-6.2 | 前端 §6.2 驗證不完整 | High→Medium | 部分接受 | 同 R2 |
| S-6.3a | 「尚無資料」只看節點 | Medium | 接受 | 同 R6 |
| S-6.3b | 非 200／非預期跳轉 | Medium→Low | 部分接受 | 同 R7 |
| S-6.3c | 前檔 schema 不符仍沿用 | High→Medium | 部分接受 | 同 R3 |
| S-6.3d | 開啟中頁面過期警示 | High | 接受 | 同 R4 |
| S-A1 | 完整原文、同日修訂流程 | High | 接受 | 同 T2 |
| S-A2 | 反例未驗沿用前檔 | Medium | 接受 | 同 T3 |
| S-A3 | 未比較前檔全部欄位 | Medium | 接受 | 補 base、success_run_id、supersedes 完整沿用斷言 |
| S-A4 | 第四筆壞、真實 HTTP 邊界 | High | 接受 | 同 T2 |
| S-A5 | 空狀態文字反例 | Medium | 接受 | 同 R6 |
| S-A6 | 未走正式流程、兩個換行未測 | Medium | 部分接受 | 兩個 `\n` 的主檔品名確實未測，接受；流程級理由見 T4 |
| S-A7 | 全形引號／`/`／`&` 未完整覆蓋 | Low | 接受 | 補明確輸入輸出 |
| S-A8 | CLI exit 1 未測 | Low | 接受 | 補 `main()` 入口測試 |
| S-A9 | 成功快照只驗部分欄位 | Medium | 接受 | 以 Python 端輸出契約驗證函式驗完整 schema（同 R3 的驗證函式） |
| S-A10 | 缺跨端（Python 產出 → TS 清洗）證據 | Medium | 部分接受 | 接受補一份 Python 實際產出的「s2 error 沿用非空恢復 additions」快照 fixture，交給 TS 測試清洗結果；不建跨語言 CI 管線 |
| S-A11 | 發布內容、base、排程 XML | High→Medium | 部分接受 | 同 T1 |
| S-A12 | 重試來源、移類、前檔沿用 | Medium | 接受 | 同 T3 |
| S-B1 | 缺清洗後集合與指紋 | High→Medium | 部分接受 | 同 T4 |
| S-B2 | — | — | 無缺口 | Codex 也判定無明顯缺漏 |
| S-B3 | 同日只驗 ID、徽章只驗 URL | Medium | 接受 | 補內容斷言；徽章渲染併入 T5 的靜態渲染測試 |
| S-B4 | 未驗渲染與 F 並存 | Medium | 部分接受 | 同 T5 |
| S-B5 | 跨時間門檻、缺欄入口 | Medium | 接受 | 同 R4、T6 |
| S-B6 | 兩檔完成順序、App 畫面 | Medium | 部分接受 | 完成順序：App 以 `await supplementLoad` 串接，兩檔順序對結果無影響可由程式結構確認；畫面列 SMOKE_TEST |
| S-B7 | 未驗導覽與區塊計數 | Medium | 部分接受 | 併入 T5 靜態渲染測試驗導覽列計數 |
| S-B8 | 未知／損壞 base 未測 | High | 接受 | 同 R1 |
| S-B9 | 互動與 console 待補 | Medium | 部分接受 | r5 §9 已承認；維持待補，不計為完成 |
| S-C1 | 沒有可追溯的獨立逐列核對產物 | High→Medium | 部分接受 | 屬實：會話中做過列表層級比對，但沒有存成檔案，`plan-supplement.md` 的「0 筆誤判」敘述目前無法追溯。補一份核對產物進 `.ai-review/`（一次性腳本＋輸出），並在規格紀錄中引用。嚴重度 Medium（實際 diff 結果與手動比對一致，缺的是證據保存） |
| S-C2 | 未執行 | Low | 接受 | 維持非阻擋 |
| S-C3 | 舊公告樣本已不可能 | Medium | 接受 | 更新 C3：第三個樣本改為核對 `excluded_no_license` 的 4 筆確為空證號 |
| S-C4 | #5／#6 紀錄沒有非空資料證據 | Medium | **接受（更正紀錄）** | 屬實，**`SMOKE_TEST.md` 的執行紀錄寫錯了**：實測時真實檔案的 s2 additions 是空的，#5「恢復公告不會間接藏掉缺藥」其實**沒有被觸發**；#6 實際驗到的是「改日期修訂的新舊並列」，不是同日修訂。須更正紀錄並以構造的非空資料重測 |

## 統計

- 共 54 項：**接受 28／部分接受 25／拒絕 0**；另 1 項（S-B2）Codex 本身判定無缺口
- 嚴重度調整：降級 15 項（主要理由：需要產出端 bug 才能觸發、或失敗是大聲的紅色而非靜默）；未升級任何項
- 規格符合度缺口（規格宣稱有、實作沒做）：A4 第四筆壞、A12(b) 移類、B1 清洗後集合、B4 渲染文字、C1 核對產物、C4 #5／#6 紀錄

## 必修項（Critical／High 且接受或部分接受）

1. **R4**：開啟中頁面的新鮮度與信任要隨時間重算（漏報風險、藥局分頁常駐是常態）
2. **R1**：無合法 base 一律不可信；`load_main()` 驗 `last_updated`；前端防 `base.last_updated` 型別錯誤崩潰
3. **T2／S-A1／S-A4**：易安穩完整原文逐字斷言；A4「第四筆壞」流程測試；`DsmsClient` 測試
4. **S-C4**：更正 `SMOKE_TEST.md` 不實紀錄，以非空恢復 additions 與同日修訂資料重測 #5、#6

## 建議處理順序

1. **R4 → R1**（前端漏報，影響已上線後的實際行為）
2. **R6、R5、R7、R3**（補抓端入口守門；R3 連帶建立「輸出契約驗證函式」，S-A9、T6 共用）
3. **R2**（前端 §6.2 縱深防禦）＋ **T6** 反例
4. **測試補強**：T2、T3（含 A12(b)）、T4（B1 清洗後）、T5（靜態渲染）、T1（真實暫存 repo）、S-A3／A6／A7／A8／A10
5. **R8** 重構（測試補齊後再動）
6. **證據與文件**：C1 核對產物、C3 條款更新、C4 更正並重測、D-3 鎖 requests 版本
7. **另案**：D-1／D-2／D-4 依賴升級（`chore(deps)`，main 既有問題）
8. 修完後依 Codex 建議**重新覆審**

---

## 處理狀態（2026-10-26）

| 項目 | 狀態 | commit |
|---|---|---|
| R4、R1 | 已修 | `1591493` |
| R6、R5、R7、R3 | 已修 | `74fa889` |
| R2、T6 | 已修 | `a371805` |
| T1–T5、S-A1／A2／A4／A6／A7／A8／A10／A12、S-B1／B3／B4 | 已補測試 | `5501fe5` |
| R8 | 已重構 | `2764a11` |
| S-C1、S-C3、S-C4、D-3 | 已補證據與文件 | 本次 docs commit |
| D-1、D-2、D-4 | 另案（main 既有） | — |
| S-B9 互動、S-C2、SMOKE #9–#13 | 待人工／待合併後 | — |
