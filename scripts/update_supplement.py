"""dsms 補抓排程包裝（增量 S，D11）：同步遠端 → 抓取 → 有變動就 commit/push → 全程留 log。

為什麼是本機排程而非 GitHub Actions：同機關的 consumer.fda.gov.tw 已證實封鎖境外 IP，
dsms 的 CI 可達性未驗證（plan-supplement.md D3）。只能在台灣網路環境的這台機器跑。

行為：
  1. 先 `git pull --rebase`——每週 CI 會自動 commit 主檔，不先同步必定 push 失敗。
  2. 跑 supplement_scraper.py。exit 0（全 ok）與 2（部分類別 error）都照常發布：
     **error 快照也要發布**，前端才看得到紅色警示；只發布成功快照的話，失敗要等
     3 天過期才被看見。exit 1（主檔不可用）＝未寫檔，不 commit。
  3. supply_supplement.json 有變動才 commit + push。push 被拒時 `pull --rebase`
     重試一次；仍失敗就結束，**不 force push**。rebase 只會帶進 CI 改的主檔，
     不改寫補抓檔內各類的 base（那是計算當時的主檔，必須如實保留）。
  4. 全程寫入 scripts/update_supplement.log。

exit 碼：0 = 全 ok 且已發布（或無變動）；2 = 部分 error 且已發布；
         3 = 發布失敗（commit 留在本機，下次一併推出）；1 = 同步失敗或主檔不可用，未發布。

手動執行（會顯示輸出）：
    uv run --with requests python scripts/update_supplement.py

排程註冊見 scripts/register_supplement_task.ps1（一律用 venv 的 pythonw.exe，
避免每日閃主控台視窗；參數理由寫在該檔）。

注意排程「執行成功」不等於「資料有更新」。真正的護欄是前端按類別的
「N 天未更新」紅色橫幅，它看的是結果。
"""
import os
import subprocess
import sys
from datetime import datetime

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
LOG_PATH = os.path.join(SCRIPTS, "update_supplement.log")
SUPPLEMENT_REL = "public/data/supply_supplement.json"
COMMIT_MESSAGE = "chore(data): 更新 dsms 公告頁補抓資料"

EXIT_OK, EXIT_ABORT, EXIT_PARTIAL, EXIT_PUBLISH_FAILED = 0, 1, 2, 3


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    # 首次建檔寫 BOM：Windows PowerShell 5.1 的 Get-Content 預設以 ANSI 讀取，
    # 無 BOM 的 UTF-8 中文會顯示成亂碼。
    encoding = "utf-8" if os.path.exists(LOG_PATH) else "utf-8-sig"
    with open(LOG_PATH, "a", encoding=encoding) as f:
        f.write(line + "\n")


# 排程以 pythonw.exe 執行（無主控台）。git 是主控台程式，由無主控台的父行程啟動時，
# Windows 會替每個子行程另開主控台視窗；CREATE_NO_WINDOW 才真正壓住閃窗。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_cmd(cmd, **kwargs):
    """執行外部指令，回傳 CompletedProcess（不自動拋例外，由呼叫端判斷）。"""
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=_NO_WINDOW, **kwargs)


def push_with_retry(run, logger):
    """push；被拒時 pull --rebase 後重試一次。永不 --force。回傳是否成功。"""
    r = run(["git", "push"])
    if r.returncode == 0:
        return True
    logger(f"push 被拒，pull --rebase 後重試一次：{r.stderr.strip()}")
    r = run(["git", "pull", "--rebase"])
    if r.returncode != 0:
        logger(f"FATAL: 重試前 pull --rebase 失敗：{r.stderr.strip()}")
        return False
    r = run(["git", "push"])
    if r.returncode != 0:
        logger(f"FATAL: 重試 push 仍失敗（先查 gh auth status）：{r.stderr.strip()}")
        return False
    return True


def main(run=run_cmd, logger=log, python=sys.executable):
    logger("=== dsms 補抓作業開始 ===")

    r = run(["git", "pull", "--rebase"])
    if r.returncode != 0:
        logger(f"FATAL: git pull --rebase 失敗，可能有未提交變更或衝突；中止：{r.stderr.strip()}")
        return EXIT_ABORT

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = run([python, os.path.join("scripts", "supplement_scraper.py")], env=env)
    for line in (r.stdout + r.stderr).splitlines():
        if line.strip():
            logger(f"  {line}")
    if r.returncode not in (EXIT_OK, EXIT_PARTIAL):
        logger(f"FATAL: supplement_scraper.py exit {r.returncode}，未寫檔，不 commit。")
        return EXIT_ABORT
    scrape_code = r.returncode

    r = run(["git", "status", "--porcelain", "--", SUPPLEMENT_REL])
    if not r.stdout.strip():
        logger("補抓檔無變動，不 commit。")
        return scrape_code

    if run(["git", "add", "--", SUPPLEMENT_REL]).returncode != 0:
        logger("FATAL: git add 失敗")
        return EXIT_PUBLISH_FAILED
    r = run(["git", "commit", "-m", COMMIT_MESSAGE, "--", SUPPLEMENT_REL])
    if r.returncode != 0:
        logger(f"FATAL: git commit 失敗：{r.stderr.strip()}")
        return EXIT_PUBLISH_FAILED
    if not push_with_retry(run, logger):
        logger("commit 已留在本機，下次執行會一併推出。")
        return EXIT_PUBLISH_FAILED

    logger("已 commit 並 push" + ("（含 error 快照）。" if scrape_code == EXIT_PARTIAL else "。"))
    logger("=== dsms 補抓作業結束 ===")
    return scrape_code


if __name__ == "__main__":
    sys.exit(main())
