# 🏥 西藥供應資訊儀表板 (NHI Drug Supply Monitor)

專為臨床醫療人員、藥局採購與藥師設計的西藥供應狀態監測面板。本系統透過自動化排程介接衛福部食藥署開放資料，提供即時、視覺化且易於檢索的藥品短缺與替代資訊。

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Click%20Here-blue?style=for-the-badge)](https://liangrxdev.github.io/TFDA-drug-shortage-dashboard/)
![License](https://img.shields.io/badge/License-MIT-blue.svg)
![React](https://img.shields.io/badge/React-19-61dafb.svg?logo=react)
![Vite](https://img.shields.io/badge/Vite-5-646cff.svg?logo=vite)
![Python](https://img.shields.io/badge/Python-3.10+-3776ab.svg?logo=python)

## ✨ 核心功能 (Features)

* **臨床導向的缺藥分級**：嚴格區分「無替代藥品 (紅)」、「有替代藥品 (黃)」與「已解除短缺 (綠)」，協助快速確立處置優先級。
* **智慧型決策輔助**：
  * 自動計算「缺藥持續天數」，精準標示長期斷鏈品項。
  * 運用正規表達式 (Regex) 自動萃取公告內文的「替代藥品建議」與「預計恢復時間」。
* **多維度數據分析 (Recharts)**：提供月度/年度的紅黃綠複合疊加長條圖 (Stacked Bar Chart)，視覺化呈現整體供應壓力與恢復彈性的趨勢變化。
* **高效率多條件篩選器**：支援以「字串 (品名/字號)」、「狀態 (紅/黃/綠)」、「公告年份」進行交集過濾，並具備自訂排序邏輯（最新公告/缺藥最久/字母排序）。
---

## 🏗️ 系統架構 (Architecture)

本專案採用 **Serverless (無伺服器) + SSG (靜態網站生成)** 架構，確保最高等級的可用性與最低的託管成本。

| 階段 | 負責元件 | 執行邏輯與技術 |
| :--- | :--- | :--- |
| **資料來源** | 衛福部開放資料 API | 端點代碼：`104` (有替代), `105` (無替代), `106` (已解除) |
| **ETL 處理** | GitHub Actions + Python | 每週五凌晨執行 `fetch_fda_data.py`，清洗資料並合併為 `supply_status_latest.json` |
| **前端渲染** | React + TypeScript + Vite | 讀取靜態 JSON，使用自訂 CSS (BEM 命名法) 渲染響應式 UI |
| **網頁託管** | GitHub Pages | 由 GitHub 全球 CDN 分發，提供極速的載入體驗 |

---
## 📜 免責聲明 (Disclaimer)
* 本系統之原始資料皆來自 政府資料開放平臺 - 衛福部食藥署。
* 本儀表板僅供介面優化與資訊檢索參考，不構成任何醫療決策指引。實際藥品供應狀態與替代方案，請務必依據各醫療機構之正式公告與臨床藥師之專業評估為準。

---
## 💻 本機開發指南 (Local Development)

若您希望在本地端運行或修改此專案，請確保您的環境已安裝 Node.js (v18+) 與 Python (v3.10+)。

### 1. 取得專案
```bash
git clone https://github.com/您的帳號/TFDA-drug-shortage-dashboard.git
cd TFDA-drug-shortage-dashboard
```

### 2. 前端開發
```bash
npm install        # 安裝相依套件
npm run dev        # 啟動本機開發伺服器
npm run build      # 型別檢查 (tsc) + Vite 打包 → dist/
npm run lint       # ESLint 檢查
```

### 3. 更新資料 (ETL)
```bash
# 抓取食藥署 104/105/106 開放資料，合併為 public/data/supply_status_latest.json
# 採 fail-closed：任一端點連線／HTTP／JSON／驗證失敗即中止，且不覆寫既有資料
uv run --with requests python scripts/fetch_fda_data.py
```

### 4. 測試
```bash
npm run test                                        # 前端資料管線單元測試 (Vitest)
uv run --with pytest --with requests pytest scripts # ETL fail-closed／schema 測試 (pytest)
```
