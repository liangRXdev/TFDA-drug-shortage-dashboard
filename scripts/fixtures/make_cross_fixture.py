"""重新產生 cross_s2_error_carried.json（A10 跨端 fixture）。

用法（repo 根目錄）：uv run --with pytest --with requests python scripts/fixtures/make_cross_fixture.py
產生後務必確認 src/lib/supplement.test.ts 的跨端測試仍通過；pytest 的
test_a10_cross_end_fixture_is_current 會在 Python 產出改變時提醒重跑本檔。
"""
import json
import os
import pathlib
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import test_supplement_scraper as t  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    snapshot = t.build_cross_snapshot(pathlib.Path(tmp))
with open(t.CROSS_FIXTURE, "w", encoding="utf-8", newline="\n") as f:
    json.dump(snapshot, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("wrote", t.CROSS_FIXTURE)
