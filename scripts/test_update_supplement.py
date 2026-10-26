# -*- coding: utf-8 -*-
"""補抓排程包裝測試（增量 S，plan-supplement.md A11）。

以假的指令執行器模擬 git 與 scraper，斷言指令序列、發布結果與 exit 碼。
執行：uv run --with pytest pytest scripts/test_update_supplement.py
"""
import os
import sys
import json
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
    """只看實際執行的程式行（去掉註解）：註解裡寫了旗標不算數（T1）。"""
    path = os.path.join(os.path.dirname(__file__), "register_supplement_task.ps1")
    with open(path, encoding="utf-8") as f:
        code = "\n".join(line.split("#", 1)[0] for line in f)
    for flag in ("-MultipleInstances IgnoreNew", "-StartWhenAvailable", "-AllowStartIfOnBatteries",
                 "-DontStopIfGoingOnBatteries", "pythonw.exe", "scripts\\update_supplement.py",
                 "-ExecutionTimeLimit", "Register-ScheduledTask"):
        assert flag in code, flag


# ----------------------------------------------------------------------
# 真實 git：暫存 work repo + bare remote，驗證遠端實際收到的檔案內容（T1）
# ----------------------------------------------------------------------
STUB_SCRAPER = '''\
import json, os, subprocess, sys
payload = os.environ["STUB_PAYLOAD"]
os.makedirs("public/data", exist_ok=True)
with open("public/data/supply_supplement.json", "w", encoding="utf-8", newline="\\n") as f:
    f.write(payload)
rival = os.environ.get("STUB_RIVAL")
if rival:   # 模擬抓取期間每週 CI 先 push 了主檔
    with open(os.path.join(rival, "public/data/supply_status_latest.json"), "w", encoding="utf-8") as f:
        f.write('{"last_updated": "2026-10-30 04:00:00", "datasets": {}}')
    subprocess.run(["git", "commit", "-qam", "chore: auto-update FDA drug supply data"], cwd=rival, check=True)
    subprocess.run(["git", "push", "-q"], cwd=rival, check=True)
sys.exit(int(os.environ.get("STUB_CODE", "0")))
'''


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def clone(tmp_path, remote, name):
    path = tmp_path / name
    git(tmp_path, "clone", "-q", str(remote), str(path))
    git(path, "config", "user.name", "test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "core.autocrlf", "false")
    return path


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    work = clone(tmp_path, remote, "work")
    (work / "public" / "data").mkdir(parents=True)
    (work / "public/data/supply_status_latest.json").write_text(
        '{"last_updated": "2026-10-23 04:53:03", "datasets": {}}', encoding="utf-8")
    (work / "scripts").mkdir()
    (work / "scripts/supplement_scraper.py").write_text(STUB_SCRAPER, encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "init")
    git(work, "push", "-q", "-u", "origin", "main")
    rival = clone(tmp_path, remote, "rival")
    return {"remote": remote, "work": work, "rival": rival}


def real_runner(cwd):
    def run(cmd, **kwargs):
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **kwargs)
    return run


def remote_file(remote, path):
    return git(remote, "show", f"main:{path}")


SNAPSHOT_ERROR = json.dumps({"schema": 1, "run_id": "R", "categories": {"s2": {"state": "error",
                             "base": {"last_updated": "2026-10-23 04:53:03"}}}}, ensure_ascii=False)


def test_real_git_error_snapshot_reaches_remote_verbatim(repos, monkeypatch):
    monkeypatch.setenv("STUB_PAYLOAD", SNAPSHOT_ERROR)
    monkeypatch.setenv("STUB_CODE", "2")
    code = wrap.main(run=real_runner(repos["work"]), logger=lambda _m: None, python=sys.executable)
    assert code == 2
    assert remote_file(repos["remote"], wrap.SUPPLEMENT_REL) == SNAPSHOT_ERROR


SNAPSHOT_ALL_OK = json.dumps({"schema": 1, "run_id": "R-OK", "categories": {
    k: {"state": "ok", "base": {"last_updated": "2026-10-23 04:53:03"}} for k in ("s2", "s3", "s4")}},
    ensure_ascii=False)


def test_real_git_all_ok_snapshot_reaches_remote_verbatim(repos, monkeypatch):
    """A11(b)（第二輪 T-R4）：三類全 ok 的快照與 error 快照各自獨立驗證，exit 0。"""
    monkeypatch.setenv("STUB_PAYLOAD", SNAPSHOT_ALL_OK)
    monkeypatch.setenv("STUB_CODE", "0")
    code = wrap.main(run=real_runner(repos["work"]), logger=lambda _m: None, python=sys.executable)
    assert code == 0
    assert remote_file(repos["remote"], wrap.SUPPLEMENT_REL) == SNAPSHOT_ALL_OK


def test_real_git_rival_push_then_retry_keeps_base_and_both_commits(repos, monkeypatch):
    """抓取期間 CI 先 push → 第一次 push 被拒 → rebase 後重試：補抓檔逐位元等於產出（base 未被改寫），
    CI 的主檔變更也保留。"""
    monkeypatch.setenv("STUB_PAYLOAD", SNAPSHOT_ERROR)
    monkeypatch.setenv("STUB_CODE", "0")
    monkeypatch.setenv("STUB_RIVAL", str(repos["rival"]))
    logs = []
    code = wrap.main(run=real_runner(repos["work"]), logger=logs.append, python=sys.executable)
    assert code == 0
    assert any("push 被拒" in line for line in logs)
    assert remote_file(repos["remote"], wrap.SUPPLEMENT_REL) == SNAPSHOT_ERROR
    assert "2026-10-30 04:00:00" in remote_file(repos["remote"], "public/data/supply_status_latest.json")
    subjects = git(repos["remote"], "log", "--format=%s", "main").splitlines()
    assert subjects[:2] == [wrap.COMMIT_MESSAGE, "chore: auto-update FDA drug supply data"]


def test_real_git_persistent_rejection_is_exit_3_and_nothing_published(repos, monkeypatch):
    hook = repos["remote"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho rejected-by-test >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setenv("STUB_PAYLOAD", SNAPSHOT_ERROR)
    monkeypatch.setenv("STUB_CODE", "0")
    code = wrap.main(run=real_runner(repos["work"]), logger=lambda _m: None, python=sys.executable)
    assert code == 3
    with pytest.raises(subprocess.CalledProcessError):
        remote_file(repos["remote"], wrap.SUPPLEMENT_REL)
    assert git(repos["work"], "log", "-1", "--format=%s").strip() == wrap.COMMIT_MESSAGE
