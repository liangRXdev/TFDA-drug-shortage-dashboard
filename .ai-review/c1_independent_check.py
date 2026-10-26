"""C1 獨立核對（一次性，不屬正式管線；verdict-supplement.md S-C1）。

刻意**不 import** scripts/supplement_scraper.py：用另一套寫法（regex 解析、自寫正規化）
重新抓 dsms 三類完整列表與 s3/s4 詳情，獨立算出與主檔的差異，再與補抓檔的
additions／supersedes 比對**單位、重數與目標列**。兩者一致才算 C1 通過。

用法（repo 根目錄，需台灣網路）：
    uv run --no-project --with requests python .ai-review/c1_independent_check.py > .ai-review/c1-check-<日期>.md
"""
import html
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

TZ = timezone(timedelta(hours=8))
CATS = [("s3", 3, "54504_with_alternative", True),
        ("s4", 4, "54505_no_alternative", True),
        ("s2", 2, "54506_resolved", False)]


def key(s):
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(ch for ch in s if not (ch.isspace() or ch in "\u200b\ufeff"))


def hidden(page):
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))


def span(page, sid):
    m = re.search(r'id="%s"[^>]*>(.*?)</span>' % re.escape(sid), page, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None


def list_rows(page):
    out = []
    for tr in re.findall(r'<tr class="grv(?:Row|AlternatingRow)">(.*?)</tr>', page, re.S):
        tds = [html.unescape(re.sub(r"<[^>]+>", "", td)).strip() for td in re.findall(r"<td.*?</td>", tr, re.S)]
        target = re.search(r"__doPostBack\(&#39;([^&]+lbtnProductNameC)&#39;", tr).group(1)
        out.append({"date": tds[0], "zh": tds[1], "case": tds[4], "target": target})
    return out


def scan(session, s):
    url = f"https://dsms.fda.gov.tw/DrugList.aspx?s={s}"
    page = session.get(url, timeout=30).text
    pages, n = [], 1
    while True:
        pages.append((page, list_rows(page)))
        if f"&#39;Page${n + 1}&#39;" not in page:
            return url, pages
        n += 1
        time.sleep(0.5)
        page = session.post(url, data=dict(hidden(page), __EVENTTARGET="ctl00$ContentPlaceHolder1$grvDrug",
                                           __EVENTARGUMENT=f"Page${n}"), timeout=30).text


def detail(session, url, page, row):
    time.sleep(0.5)
    d = session.post(url, data=dict(hidden(page), __EVENTTARGET=row["target"], __EVENTARGUMENT=""), timeout=30).text
    hist = []
    i = 0
    while span(d, f"ContentPlaceHolder1_grvPublishList_lblPublishContent_{i}") is not None:
        raw = re.search(r'id="ContentPlaceHolder1_grvPublishList_lblPublishContent_%d"[^>]*>(.*?)</span>' % i,
                        d, re.S).group(1)
        hist.append((span(d, f"ContentPlaceHolder1_grvPublishList_lblPublishUpdateTime_{i}"),
                     html.unescape(re.sub(r"<[^>]+>", "", raw))))
        i += 1
    newest = max(h[0] for h in hist)
    return {"license": span(d, "ContentPlaceHolder1_lblLicense") or "",
            "case": span(d, "ContentPlaceHolder1_lblSystemNo"),
            "newest": newest, "text": [h[1] for h in hist if h[0] == newest][0]}


def main():
    # 報告一律 UTF-8：Windows 主控台預設 cp950，且 `python -I` 會忽略 PYTHONIOENCODING
    sys.stdout.reconfigure(encoding="utf-8")
    start = datetime.now(TZ)
    main_file = json.load(open("public/data/supply_status_latest.json", encoding="utf-8"))
    supp = json.load(open("public/data/supply_supplement.json", encoding="utf-8"))
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (C1 independent check)"
    obs_path = f".ai-review/c1-observations-{start:%Y-%m-%d}.jsonl"
    obs = open(obs_path, "w", encoding="utf-8", newline="\n")
    obs.write(json.dumps({"type": "header", "started_at": start.isoformat(timespec="seconds"),
                          "main_last_updated": main_file["last_updated"], "supplement_run_id": supp["run_id"],
                          "bases": {k: v.get("base") for k, v in supp["categories"].items()}},
                         ensure_ascii=False) + "\n")
    print(f"# C1 獨立核對\n\n- 起：{start.isoformat(timespec='seconds')}")
    print(f"- 主檔 last_updated：{main_file['last_updated']}；補抓檔 run_id：{supp['run_id']}")
    print(f"- 逐列觀測：`{obs_path}`（每列一筆網站觀測，含案件編號、日期、品名；s3/s4 另含證號與內容指紋）\n")
    all_ok = True
    for cat, s, dataset, content in CATS:
        url, pages = scan(session, s)
        rows = []
        for page, prow in pages:
            for r in prow:
                if content:
                    d = detail(session, url, page, r)
                    assert d["case"] == r["case"] and d["newest"] == r["date"], (cat, r["case"])
                    r.update(d)
                rows.append(r)
        for r in rows:
            record = {"type": "row", "category": cat, "case": r["case"], "date": r["date"], "zh": r["zh"]}
            if content:
                record.update(license=r["license"], fingerprint=key(r["text"]))
            obs.write(json.dumps(record, ensure_ascii=False) + "\n")
        excluded = [r for r in rows if content and not r["license"].strip()]
        rows = [r for r in rows if not (content and not r["license"].strip())]

        def unit_site(r):
            u = (key(r["zh"]), r["date"])
            return u + (key(r["license"]), key(r["text"])) if content else u

        def unit_main(o):
            u = (key(o["中文品名"].split("\n")[0]), o["公告更新時間"])
            return u + (key(o["許可證字號"]), key(o["供應狀態"])) if content else u

        site_c = Counter(unit_site(r) for r in rows)
        main_c = Counter(unit_main(o) for o in main_file["datasets"][dataset])
        exp_add = site_c - main_c
        exp_sup = main_c - site_c
        c = supp["categories"][cat]
        got_add = Counter((key(a["中文品名"].split("\n")[0]), a["公告更新時間"])
                          + ((key(a["許可證字號"]), key(a["供應狀態"])) if content else ()) for a in c["additions"])
        got_sup = Counter((e["品名鍵"], e["公告更新時間"]) + ((key(e["許可證字號"]), e["指紋"]) if content else ())
                          for e in c["supersedes"])
        # 案件身分（第二輪 S-R1）：單位一致還不夠——每筆 addition 的案件編號必須就是網站上
        # 同一單位那一列的案件編號，且 編號 = dsms-<案件編號>；每筆 supersede 必須對到主檔的實際列
        site_cases = {}
        for r in rows:
            site_cases.setdefault(unit_site(r), []).append(r["case"])
        main_rows = {}
        for o in main_file["datasets"][dataset]:
            main_rows.setdefault(unit_main(o), []).append(o["編號"])
        identity_problems = []
        for a in c["additions"]:
            u = (key(a["中文品名"].split("\n")[0]), a["公告更新時間"]) \
                + ((key(a["許可證字號"]), key(a["供應狀態"])) if content else ())
            if a["_案件編號"] not in site_cases.get(u, []) or a["編號"] != f"dsms-{a['_案件編號']}":
                identity_problems.append(f"addition {a['編號']} 的案件編號不是網站上該列（網站：{site_cases.get(u)}）")
        sup_targets = []
        for e in c["supersedes"]:
            u = (e["品名鍵"], e["公告更新時間"]) + ((key(e["許可證字號"]), e["指紋"]) if content else ())
            targets = main_rows.get(u, [])
            if not targets:
                identity_problems.append(f"supersede {e['公告更新時間']} {e['品名鍵']} 對不到主檔任何一列")
            sup_targets.append((e, targets))
        ok = exp_add == got_add and exp_sup == got_sup and not identity_problems \
            and sorted(r["case"] for r in excluded) == sorted(e["_案件編號"] for e in c.get("excluded_no_license", []))
        all_ok &= ok
        print(f"## {cat}（{dataset}）：{'一致' if ok else '**不一致**'}\n")
        print(f"- 網站 {len(rows) + len(excluded)} 筆（{len(pages)} 頁），空證號排除 {len(excluded)}："
              f"{sorted(r['case'] for r in excluded)}")
        print(f"- 主檔 {sum(main_c.values())} 筆；網站與主檔相同單位 {sum((site_c & main_c).values())} 筆")
        print(f"- 獨立算出 additions {sum(exp_add.values())}、supersedes {sum(exp_sup.values())}；"
              f"補抓檔 additions {len(c['additions'])}、supersedes {len(c['supersedes'])}")
        for u, n in sorted(exp_add.items()):
            print(f"  - ＋ {u[1]} {u[0]}" + (f" {u[2]}" if content else "") + (f" ×{n}" if n > 1 else ""))
        for u, n in sorted(exp_sup.items()):
            print(f"  - － {u[1]} {u[0]}" + (f" {u[2]}" if content else "") + (f" ×{n}" if n > 1 else ""))
        for a in c["additions"]:
            print(f"  - 補抓 addition `{a['編號']}`：案件 {a['_案件編號']} ＝ 網站同單位列的案件編號")
        for e, targets in sup_targets:
            print(f"  - 補抓 supersede {e['公告更新時間']} {e['品名鍵']} → 主檔列 編號 {targets}")
        for p in identity_problems:
            print(f"  - **案件身分問題**：{p}")
        if not ok:
            print(f"  - 差異：獨立多 {dict(exp_add - got_add)}／{dict(exp_sup - got_sup)}；"
                  f"補抓多 {dict(got_add - exp_add)}／{dict(got_sup - exp_sup)}")
        print()
    obs.close()
    print(f"- 迄：{datetime.now(TZ).isoformat(timespec='seconds')}")
    print(f"\n**結論：{'C1 通過' if all_ok else 'C1 未通過'}**")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
