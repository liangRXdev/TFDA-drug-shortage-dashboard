# 🏥 NHI Drug Supply Monitor (西藥供應資訊儀表板)

**English** | [繁體中文](README.zh-TW.md)

A drug supply monitoring dashboard designed for clinical staff, pharmacy purchasing and pharmacists. An automated schedule ingests open data from the Taiwan Food and Drug Administration (TFDA) and presents drug shortage and alternative information in a timely, visual and easily searchable form. The interface is in Traditional Chinese.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Click%20Here-blue?style=for-the-badge)](https://liangrxdev.github.io/TFDA-drug-shortage-dashboard/)
![License](https://img.shields.io/badge/License-MIT-blue.svg)
![React](https://img.shields.io/badge/React-19-61dafb.svg?logo=react)
![Vite](https://img.shields.io/badge/Vite-5-646cff.svg?logo=vite)
![Python](https://img.shields.io/badge/Python-3.10+-3776ab.svg?logo=python)

## ✨ Features

* **Clinically oriented shortage grading**: strictly separates "no alternative (red)", "alternative available (yellow)" and "shortage resolved (green)" to help set handling priorities quickly.
* **Decision support**:
  * Automatically computes "days in shortage", clearly flagging long-running supply breaks.
  * Uses regular expressions to extract "suggested alternatives" and "expected recovery date" from announcement text.
* **Multi-dimensional analysis (Recharts)**: monthly/yearly red-yellow-green stacked bar charts visualize trends in overall supply pressure and recovery resilience.
* **Efficient multi-criteria filters**: intersect filters by text (product name / license number), status (red/yellow/green) and announcement year, with custom sort orders (latest announcement / longest shortage / alphabetical).
* **Two independent staleness warnings**: separately detect two failure modes where "the screen is stuck in the past"; they are independent signals and can show at the same time.
  * **Schedule stopped** — warns when `last_updated` hasn't advanced for more than 10 days (GitHub automatically disables schedules in long-inactive repos).
  * **Upstream stale** — prompts when the schedule is running but the TFDA's latest announcement date hasn't advanced for 4 consecutive observation periods. This is a **suspicion signal, not proof of staleness**: same-day revisions, corrections to old announcements and a single endpoint going stale won't trigger it.

---

## 🏗️ Architecture

The project uses a **serverless + SSG (static site generation)** architecture for the highest availability and lowest hosting cost.

| Stage | Component | Logic and technology |
| :--- | :--- | :--- |
| **Data source** | Ministry of Health and Welfare open data API | Endpoint codes: `104` (alternative available), `105` (no alternative), `106` (resolved) |
| **ETL** | GitHub Actions + Python | Runs `fetch_fda_data.py` early every Friday morning, cleaning data and merging it into `supply_status_latest.json`. Fail-closed, and serialized with a `concurrency` group (only one copy of cross-run state) |
| **Frontend rendering** | React + TypeScript + Vite | Reads static JSON and renders a responsive UI with custom CSS (BEM naming) |
| **Hosting** | GitHub Pages | Served from GitHub's global CDN for fast loading |

### Data file format (`public/data/supply_status_latest.json`)

```jsonc
{
  "last_updated": "2026-09-08 12:04:33",  // last successful ETL "check" time; advances on every successful run
  "upstream_max_date": "2026/08/31",       // latest upstream announcement date; null means no baseline to compare
  "frozen_runs": 0,                         // consecutive observation periods without the upstream date advancing
  "last_observed_period": "2026-W37",      // counting unit: ISO week in Taiwan time (reruns in the same week don't count)
  "datasets": { }
}
```

⚠️ **`last_updated` only means "checked", not "data updated".** To judge whether upstream is still moving, look at
`upstream_max_date` / `frozen_runs`; the two semantics must not be mixed. The last three fields are optional;
if an older data file lacks them the frontend disables the stale-upstream prompt rather than erroring.

---
## 📜 Disclaimer
* All raw data come from the Government Open Data Platform – Taiwan Food and Drug Administration.
* This dashboard is only an improved interface for information lookup and does not constitute medical decision guidance. For actual drug supply status and alternatives, always rely on your institution's official announcements and the professional assessment of clinical pharmacists.

---
## 💻 Local Development

To run or modify the project locally, make sure Node.js (v18+) and Python (v3.10+) are installed.

### 1. Get the project
```bash
git clone https://github.com/<your-account>/TFDA-drug-shortage-dashboard.git
cd TFDA-drug-shortage-dashboard
```

### 2. Frontend
```bash
npm install        # install dependencies
npm run dev        # start the local dev server
npm run build      # type check (tsc) + Vite build → dist/
npm run lint       # ESLint
```

### 3. Update data (ETL)
```bash
# Fetch TFDA 104/105/106 open data and merge into public/data/supply_status_latest.json
# Fail-closed: any connection / HTTP / JSON / validation failure on any endpoint aborts without overwriting existing data
uv run --with requests python scripts/fetch_fda_data.py
```

### 4. Tests
```bash
npm run test                                        # frontend data-pipeline unit tests (Vitest, 103 cases)
uv run --with pytest --with requests pytest scripts # ETL fail-closed / schema / stale detection (pytest, 75 cases)
```

### 5. Specs and review records

`.ai-review/` keeps each increment's spec, raw Codex independent-review output and item-by-item verdicts.
Before changing a feature, read the "non-goals" section of its spec — it is the anchor against scope creep.

| Increment | Spec | Review / verdict |
| :--- | :--- | :--- |
| Whole-repo code review (CR-01–CR-14) | — | `codex-review.md` / `verdict.md` / `remediation-log.md` |
| Upstream stale detection (F1–F15b) | `plan-upstream-freeze.md` | `plan-review-upstream-freeze.md` / `plan-verdict-upstream-freeze.md` |
