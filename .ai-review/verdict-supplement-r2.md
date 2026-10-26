# 覆審判定：第二輪（增量 S 修正後）

> 對象：`codex-review-supplement-r2.md`（Codex，2026-10-26，commit `5250f5a`）。判定者：Claude。
> 每項回到檔案原處驗證；行號以 `5250f5a` 為準。

## 區塊 0：修正驗證的確認

Codex 確認已修：R2、R5、R6、R7、R8、S-A6、S-A8、S-A10、D-3；T1、T2 主要缺口已修。
以下只判定「部分／未完成」與新發現。

## 判定表

| # | 項目 | 嚴重度 | 判定 | 理由 |
|---|------|--------|------|------|
| N1 | 非法 base 時間（合法前綴＋任意尾碼）仍被信任 | Medium | **接受** | `src/lib/dataPipeline.ts:84` 的 `parseLastUpdated` regex 沒有 `$` 錨點，`2026-10-23 04:53:03garbage` 解析成功；`src/lib/supplement.ts` 的 `baseStatus()` 直接用它。第一輪 R1 的修法只擋了 null／`bad`／錯型別，弱化實作仍能通過——Codex 指出的正是假綠燈形態。修法：補抓端 base 改用完整錨定的嚴格格式驗證（不改 `parseLastUpdated` 既有行為，它服務主檔 CR-06），加尾碼與超界時分秒反例 |
| N2a | Python 前檔／輸出契約沒有未來日期上限 | Medium | **接受** | `scripts/supplement_scraper.py:703` 只用 `parse_date()`（真實曆日），沒有前端 `isValidAnnouncementDate` 的「台灣今天＋1 天」上限；前檔含 `2099/01/01` 時 Python 沿用、前端整份拒收，R3 的故障隔離仍破。**第一輪的測試用 `2099/13/01`，擋下它的是月份不存在，不是未來日期——我的測試錨錯位置**。修法：`output_problems(payload, today)` 帶執行日期，additions 與 supersedes 都驗上限；測試改用合法曆日的未來日期 |
| N2b | Python 未驗 `base.upstream_max_date` 型別 | Low | **接受** | `category_problems()` 只驗 `base.last_updated`；前端 `isCategory` 要求 `upstream_max_date` 為 string／null／undefined。補驗以對齊前端 |
| N2c | 主檔錯誤日期進入 supersedes → 最後整批拋錯，其他類與 error 快照都不發布 | Medium | **接受** | `load_main()` 只驗欄位是字串；主檔 104 某列日期壞掉、且該列被 supersede 時，`output_problems()` 在寫檔前 raise，整批不寫——退化成「三類都沒更新」，比單類 error 更差。ETL 端 `fetch_fda_data.py` 對無效日期只告警不阻擋（`has_invalid`），所以主檔確實可能出現無效日期。修法：`process_category` 內主檔列日期無效 → 該類 ScrapeError（單類隔離），不等到寫檔前 |
| T-R1 | A2／A3／A12 沿用與 orchestration 仍可假綠燈 | Medium | **接受** | `test_a2_scan_errors_keep_previous_results` 只比 additions；A12(a)(b) 從無前檔開始，「不一致時清空前檔」的實作也會通過；A12(d) 只比 `_signature()`；A3 的完整沿用只測 s2 且 supersedes 為空。修法：共用「非空 additions＋非空 supersedes 的成功前檔」輔助，A2／A3／A12 全部走 `run()` 並比對全部沿用欄位 |
| T-R2 | App 接線（R4 計時器、B6 兩檔順序）、B7 畫面計數、徽章渲染未測 | Medium | **部分接受** | 屬實：`src/App.tsx` 的 timer／focus／visibilitychange 被刪除，現有測試仍綠；徽章與導覽計數沒有任何渲染測試。Codex 對第一輪 S-B6 判定的異議成立：§9 只延期 B9，B6／B7 不該以「程式結構可確認」帶過。**修法分兩層**：（1）徽章與導覽計數抽成純元件，以既有 `react-dom/server` 靜態渲染驗證（不加依賴）；（2）App 接線（計時器、兩檔載入順序）需要能執行 effect 的測試環境——要加 `jsdom`＋`@testing-library/react` 兩個 devDependency，**屬於使用者決策**。不加的話，在規格 §9 明列延期並由 SMOKE #12 人工驗 |
| T-R3 | B1 兩階段未比日期、品名、來源、theme | Low→**Low** | **接受** | `src/lib/supplement.test.ts:118` 清洗後只比 ID、供應狀態、證號。改成比對包含日期、品名、證號、供應狀態、來源的明確投影，清洗後另比 theme。嚴重度 Low（fixture 的期望已獨立寫定，風險在漏比欄位） |
| T-R4a | A9 成功快照只驗少數欄位 | Low | **接受** | 改為以 `output_problems()`＋逐類鍵集合完整比對 |
| T-R4b | A7 缺英文全形引號 | Low | **接受** | 補 `＂`（U+FF02）向量 |
| T-R4c | A11(b) 真實 git 的 exit 0 案例發布的是 error 快照 | Low | **接受** | 補三類全 ok 的合法快照逐位元發布比較 |
| S-R1 | C1「單位一致」被擴張宣稱為完整逐列核對；沒有案件對應與逐列觀測檔 | Medium | **接受** | `.ai-review/c1_independent_check.py:118` 的 `got_add` 不含 `_案件編號`，換掉案件編號仍判一致；報告只存摘要，「237 筆內容相同」無法追溯。**規格紀錄裡寫「C1 通過」是過度宣稱**。修法：加入 addition 的案件身分核對；輸出完整逐列 JSONL 觀測（三類、含指紋與 base、run_id、時間）；重跑；在此之前把規格紀錄改為「單位與重數一致；案件對應與逐列證據待補」 |
| S-D10 等 | 同 N1 | Medium | 接受 | — |
| S-D4 等 | 同 N2 | Medium | 接受 | — |
| S-B3–B7 | 同 T-R2 | Medium | 部分接受 | 同 T-R2 |
| S-C3 | 人工驗收未完成 | Medium | **接受（無程式動作）** | 屬實；本來就待使用者，不得標記完成 |
| S-C4 | 離線情境未實測 | Medium | **接受（無程式動作）** | 屬實；SMOKE #9–#11 待人工 |
| Dep | Vite／Vitest／pandas | Medium／Low | **部分接受** | 同第一輪 D-1／D-2／D-4：main 既有問題，另案；Codex 也同意不單獨阻擋 S |

## 統計

- 判定 17 項：**接受 14（含 2 項無程式動作）／部分接受 3／拒絕 0**
- 我第一輪判定被推翻 2 處：S-B6／S-B7 不該以結構檢視帶過（T-R2）；C1 宣稱過度（S-R1）
- 我第一輪測試錨錯位置 1 處：`2099/13/01` 驗到的是無效月份而非未來日期（N2a）

## 必修項

本輪沒有 Critical／High。Medium 中直接影響「漏報或整批不發布」的三項優先：

1. **N1**：嚴格驗證 base 時間格式（假可信 → 不當隱藏）
2. **N2a／N2c**：Python 契約補未來日期上限；主檔無效日期改為單類 error（故障隔離）
3. **S-R1**：C1 補案件對應與逐列觀測，並先修正規格紀錄的過度宣稱

## 建議處理順序

1. N1 → N2a／N2b／N2c（實作）
2. T-R1、T-R3、T-R4（測試補強，無新依賴）
3. T-R2 第 (1) 層：徽章與計數抽元件＋靜態渲染
4. S-R1：C1 腳本補強並重跑連網核對（約 3 分鐘）
5. **待使用者決定**：T-R2 第 (2) 層要不要加 `jsdom`＋`@testing-library/react`
6. 人工：C3、SMOKE #9–#13；另案：npm 依賴升級
