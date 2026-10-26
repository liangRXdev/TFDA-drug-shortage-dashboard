# 手動 Smoke Test 清單

> 補 vitest／pytest 測不到的瀏覽器行為。改動 `src/lib/supplement.ts`、`App.tsx` 的載入或橫幅邏輯、
> `vite.config.ts` 的 PWA 快取規則後執行。

## 前置
- `npm run build` 後 `npx vite preview --port 4174`，開 `http://localhost:4174/TFDA-drug-shortage-dashboard/`
- 情境用改寫 `dist/data/supply_supplement.json` 模擬（只動 build 產物，不動 `public/data/`）
- 每輪測試前如需乾淨狀態：DevTools → Application → Storage → **Clear site data**

## 公告頁補抓（SUP，增量 S，規格 `.ai-review/plan-supplement.md` C4）

每項寫明操作與預期可見結果。「有替代 N」指導覽列計數。

| # | 操作 | 預期 |
|---|---|---|
| 1 | 正常（補抓檔三類 ok、同一次執行、新鮮） | 琥珀橫幅「表中 X 筆較新公告…Y 筆舊版公告已依官網隱藏」；補抓列帶「公告頁補抓」徽章，連到該類官網列表、新分頁開啟；修訂案件只出現新版 |
| 2 | 刪除補抓檔 | 紅色「無法載入公告頁補抓資料…切勿據此判定『沒有新缺藥』」；主資料照常渲染，計數等於只有 opendata；沒有任何徽章 |
| 3 | 某類 `last_success_at` 改成 4 天前 | 紅色「「該類」類補抓資料已 4 天未更新」＋「新舊版本並列」；修訂案件的舊版**沒有**被隱藏 |
| 4 | 某類 `state` 改 `error`，前檔 supersedes 非空 | 紅色指名類別與錯誤原因；舊版不被隱藏（計數比 #1 多出 supersedes 的筆數） |
| 5 | `s2` 改 `error`，additions 含某缺藥的恢復公告 | 該缺藥仍在有替代／無替代區，不會被已恢復公告間接藏掉 |
| 6 | 同日修訂並列（#3 或 #4 狀態下） | 新舊兩版都在；紅色文案含「同一藥品可能有新舊版本並列，供應說明請以官網為準」 |
| 7 | 三類 additions／supersedes 全清空 | 不顯示任何補抓橫幅 |
| 8 | 各類 `base.last_updated` 改成比主檔 `last_updated` 新 | 每類一條紅色「版本不一致，請重新整理頁面」；不隱藏 |
| 9 | 先線上載入一次 → DevTools Offline → 重載（有快取、新鮮） | 顯示快取資料，補抓橫幅與 #1 相同 |
| 10 | 同 #9，但快取的補抓檔已過期（先把 `last_success_at` 改舊再載入一次） | 離線時一樣亮紅「N 天未更新」，不會被當成最新 |
| 11 | Clear site data → Offline → 重載（無快取） | 主資料載入失敗頁（既有行為）；不會出現「沒有缺口」的假象 |

### 執行紀錄
- **2026-10-26**（`feat/dsms-supplement`，Claude 以 Chrome 實測）：#1、#2、#3（s2 4 天前）、#4／#5／#6（s2 error）、#7、#8 通過。
  實測計數：正常 239；s2 error／過期／版本不一致 240（舊版滅必治 05/07 保留）；無差異與補抓檔缺失 237。
  #9–#11（離線）未測：瀏覽器擴充無法切換 DevTools Offline，待人工補測。
