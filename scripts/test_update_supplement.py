# -*- coding: utf-8 -*-
"""補抓排程包裝測試（增量 S，plan-supplement.md A11）。

以假的指令執行器模擬 git 與 scraper，斷言指令序列、發布結果與 exit 碼。
執行：uv run --with pytest pytest scripts/test_update_supplement.py
"""
import os
import sys
import subprocess

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import update_supplement as wrap  # noqa: E402


class FakeRunner:
    """依指令前綴回傳預先排好的結果；remote 模擬遠端最後收到的 commit。"""

    def __init__(self, scrape_code=0, changed=True, push_results=(0,), pull_results=(0,)):
        self.scrape_code = scrape_code
        self.changed = changed
        self.push_results = list(push_results)
        self.pull_results = list(pull_results)
        self.calls = []
        self.remote = []        # 成功 push 時推出的 commit 訊息
        self.local = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        code, out = 0, ""
        if cmd[:2] == ["git", "pull"]:
            code = self.pull_results.pop(0) if self.pull_results else 0
        elif cmd[0] != "git":
            code = self.scrape_code
        elif cmd[:2] == ["git", "status"]:
            out = " M public/data/supply_supplement.json\n" if self.changed else ""
        elif cmd[:2] == ["git", "commit"]:
            self.local.append(cmd[3])
        elif cmd[:2] == ["git", "push"]:
            code = self.push_results.pop(0) if self.push_results else 0
            if code == 0:
                self.remote.extend(self.local)
                self.local = []
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr="rejected" if code else "")


def run_main(runner):
    logs = []
    code = wrap.main(run=runner, logger=logs.append, python="python")
    return code, logs


def test_all_ok_published():
    r = FakeRunner(scrape_code=0)
    code, _ = run_main(r)
    assert code == 0 and r.remote == [wrap.COMMIT_MESSAGE]


def test_partial_error_snapshot_still_published():
    r = FakeRunner(scrape_code=2)
    code, logs = run_main(r)
    assert code == 2 and r.remote == [wrap.COMMIT_MESSAGE]
    assert any("error 快照" in line for line in logs)


def test_push_rejected_then_retry_succeeds_without_force():
    r = FakeRunner(push_results=(1, 0))
    code, _ = run_main(r)
    assert code == 0 and r.remote == [wrap.COMMIT_MESSAGE]
    git = [c for c in r.calls if c[0] == "git"]
    assert [c[1] for c in git] == ["pull", "status", "add", "commit", "push", "pull", "push"]
    assert not any("--force" in c or "-f" in c for c in r.calls)


def test_retry_does_not_rewrite_supplement_file():
    """rebase 後不重寫補抓檔：重試路徑上不得再跑 scraper，也不得再 add/commit。"""
    r = FakeRunner(push_results=(1, 0))
    run_main(r)
    after_first_push = r.calls[r.calls.index(["git", "push"]) + 1:]
    assert all(c[0] == "git" and c[1] in ("pull", "push") for c in after_first_push)


def test_push_still_rejected_is_publish_failure():
    r = FakeRunner(push_results=(1, 1))
    code, logs = run_main(r)
    assert code == 3 and r.remote == [] and r.local == [wrap.COMMIT_MESSAGE]
    assert any("留在本機" in line for line in logs)


def test_main_file_unusable_no_commit():
    r = FakeRunner(scrape_code=1)
    code, _ = run_main(r)
    assert code == 1
    assert not any(c[:2] in (["git", "add"], ["git", "commit"], ["git", "push"]) for c in r.calls)


def test_initial_pull_failure_aborts_before_scraping():
    r = FakeRunner(pull_results=(1,))
    code, _ = run_main(r)
    assert code == 1 and len(r.calls) == 1


def test_unchanged_file_no_commit():
    r = FakeRunner(changed=False, scrape_code=2)
    code, _ = run_main(r)
    assert code == 2 and not any(c[:2] == ["git", "commit"] for c in r.calls)


def test_commit_only_supplement_file():
    r = FakeRunner()
    run_main(r)
    add = next(c for c in r.calls if c[:2] == ["git", "add"])
    commit = next(c for c in r.calls if c[:2] == ["git", "commit"])
    assert add[-1] == wrap.SUPPLEMENT_REL and commit[-1] == wrap.SUPPLEMENT_REL


def test_scheduled_task_settings():
    path = os.path.join(os.path.dirname(__file__), "register_supplement_task.ps1")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for flag in ("-MultipleInstances IgnoreNew", "-StartWhenAvailable", "-AllowStartIfOnBatteries",
                 "-DontStopIfGoingOnBatteries", "pythonw.exe", "scripts\\update_supplement.py"):
        assert flag in text, flag
