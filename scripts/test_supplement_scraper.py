# -*- coding: utf-8 -*-
"""dsms 補抓測試（增量 S，plan-supplement.md §7 A1–A12）。

無網路依賴：真實頁面以 scripts/fixtures/dsms/ 的存檔 HTML 驗證解析；
掃描、翻頁、兩輪比對與跨次序列以合成頁面＋FakeClient 驗證。
執行：uv run --with pytest --with requests pytest scripts/test_supplement_scraper.py
"""
import os
import sys
import json
import random
from datetime import datetime, date

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import supplement_scraper as sup  # noqa: E402

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures", "dsms")
TODAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 9, 10, 0, tzinfo=sup.TAIPEI_TZ)

with open(os.path.join(HERE, "fixtures", "supplement_cases.json"), encoding="utf-8") as _f:
    SHARED = json.load(_f)


def read_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


# ----------------------------------------------------------------------
# 合成頁面：結構比照 2026-10-26 存檔的 dsms 頁面
# ----------------------------------------------------------------------
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def list_row_html(i, row):
    target = f"ctl00$ContentPlaceHolder1$grvDrug$ctl{i + 2:02d}$lbtnProductNameC"
    return (
        f'<tr class="{"grvRow" if i % 2 == 0 else "grvAlternatingRow"}">'
        f'<td><span id="ContentPlaceHolder1_grvDrug_lblPublishUpdateTime_{i}">{row["date"]}</span></td>'
        f'<td><a id="ContentPlaceHolder1_grvDrug_lbtnProductNameC_{i}" '
        f"href=\"javascript:__doPostBack(&#39;{target}&#39;,&#39;&#39;)\">{esc(row['zh'])}</a></td>"
        f'<td><a href="#">{esc(row.get("en", ""))}</a></td>'
        f'<td class="hidden-xs"><a href="#">申請商</a></td>'
        f'<td class="hidden-xs">{row["case"]}</td></tr>'
    )


def pager_html(current, total):
    """比照 ASP.NET GridView：每 10 頁一組，組外以 `...` 連到相鄰組（見 list_s3_p11.html）。"""
    def link(n, label):
        return (f"<td><a href=\"javascript:__doPostBack(&#39;ctl00$ContentPlaceHolder1$grvDrug"
                f"&#39;,&#39;Page${n}&#39;)\">{label}</a></td>")
    start = (current - 1) // 10 * 10 + 1
    end = min(start + 9, total)
    cells = [link(start - 1, "...")] if start > 1 else []
    for n in range(start, end + 1):
        cells.append(f"<td><span>{n}</span></td>" if n == current else link(n, n))
    if end < total:
        cells.append(link(end + 1, "..."))
    return f'<tr align="center"><td colspan="5"><table><tr>{"".join(cells)}</tr></table></td></tr>'


def list_html(category, rows, current=None, total=None, empty=False, title=None, viewstate="vs"):
    title = title if title is not None else sup.CATEGORIES[category]["title"]
    body = "".join(list_row_html(i, r) for i, r in enumerate(rows))
    if empty:
        body = ('<tr><td colspan="5"><div><span id="ContentPlaceHolder1_grvDrug_lbEmpty">尚無資料'
                "</span></div></td></tr>")
    pager = pager_html(current, total) if current is not None else ""
    return (
        f'<html><body><form><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="{viewstate}" />'
        f'<h3><span id="ContentPlaceHolder1_lblTitle">{title}</span></h3>'
        f'<table id="ContentPlaceHolder1_grvDrug"><tr class="grvHeader"><th>更新日期</th></tr>'
        f"{body}{pager}</table></form></body></html>"
    )


def detail_html(case, zh, en, license_no, history):
    rows = "".join(
        f'<tr><td><span id="ContentPlaceHolder1_grvPublishList_lblPublishShortageCause_{i}">原因</span></td>'
        f'<td><span id="ContentPlaceHolder1_grvPublishList_lblPublishContent_{i}">{esc(text)}</span></td>'
        f'<td><span id="ContentPlaceHolder1_grvPublishList_lblPublishUpdateTime_{i}">{d}</span></td></tr>'
        for i, (d, text) in enumerate(history)
    )
    return (
        f'<html><body><span id="ContentPlaceHolder1_lblSystemNo">{case}</span>'
        f'<span id="ContentPlaceHolder1_lblProductNameC">{esc(zh)}</span>'
        f'<span id="ContentPlaceHolder1_lblProductNameE">{esc(en)}</span>'
        f'<span id="ContentPlaceHolder1_lblLicense">{esc(license_no)}</span>'
        f'<table id="ContentPlaceHolder1_grvPublishList"><tbody>{rows}</tbody></table></body></html>'
    )


def drug(case, d, zh, en="EN", license_no="衛署藥製字第000001號", text="說明", history=None):
    """一筆網站公告：列表欄位＋詳情內容。"""
    return {"case": case, "date": d, "zh": zh, "en": en, "license": license_no,
            "history": history or [(d, text)]}


class FakeSite:
    """模擬 dsms：每類一份公告清單（新→舊），可在第 n 次觀測時換內容。"""

    def __init__(self, categories, page_size=sup.PAGE_SIZE):
        self.categories = categories  # {category: [drug, ...]} 或 callable(pass_no) -> list
        self.page_size = page_size
        self.overrides = {}           # (category, page) -> html，用來注入破損頁
        self.detail_overrides = {}    # case -> html
        self.list_calls = 0

    def drugs(self, category):
        value = self.categories.get(category, [])
        return value(self.list_calls) if callable(value) else value

    def page(self, category, n):
        if (category, n) in self.overrides:
            return self.overrides[(category, n)]
        drugs = self.drugs(category)
        if not drugs:
            return list_html(category, [], empty=True)
        total = (len(drugs) + self.page_size - 1) // self.page_size
        chunk = drugs[(n - 1) * self.page_size:n * self.page_size]
        current = n if total > 1 else None
        return list_html(category, chunk, current=current, total=total,
                         viewstate=f"{category}-p{n}")

    def detail(self, category, viewstate, target):
        page_no = int(viewstate.split("-p")[1])
        index = int(target.split("$ctl")[1].split("$")[0]) - 2
        d = self.drugs(category)[(page_no - 1) * self.page_size + index]
        if d["case"] in self.detail_overrides:
            return self.detail_overrides[d["case"]]
        return detail_html(d["case"], d["zh"], d["en"], d["license"], d["history"])


class FakeClient:
    def __init__(self, site):
        self.site = site
        self.requests = []

    def get_list(self, category):
        if category == sup.SCAN_ORDER[0]:
            self.site.list_calls += 1
        self.requests.append((category, 1))
        return self.site.page(category, 1)

    def postback(self, category, hidden, target, argument):
        n = int(argument.split("$")[1])
        self.requests.append((category, n))
        return self.site.page(category, n)

    def open_detail(self, category, hidden, target):
        return self.site.detail(category, hidden["__VIEWSTATE"], target)


def main_file(tmp_path, datasets=None, last_updated="2026-10-23 04:53:03"):
    data = {"last_updated": last_updated, "upstream_max_date": "2026/10/07", "frozen_runs": 1,
            "datasets": {"54504_with_alternative": [], "54505_no_alternative": [],
                         "54506_resolved": [], **(datasets or {})}}
    path = tmp_path / "supply_status_latest.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def opendata_row(no, d, zh, en="EN", license_no="衛署藥製字第000001號", text="說明"):
    return {"編號": no, "公告更新時間": d, "中文品名": f"{zh}\n{en}", "許可證字號": license_no,
            "供應狀態": text}


def run_once(tmp_path, site, main_path, now=NOW):
    out = str(tmp_path / "supply_supplement.json")
    code = sup.run(main_path=main_path, output_path=out, client=FakeClient(site), now=now)
    with open(out, encoding="utf-8") as f:
        return code, json.load(f)


def drugs_n(n, start_case=2000000, d0=(2026, 9, 1)):
    """n 筆日期非遞增的背景公告。"""
    out = []
    for i in range(n):
        day = max(1, 28 - i // 3)
        out.append(drug(str(start_case + i), f"{d0[0]}/{d0[1]:02d}/{day:02d}", f"背景藥{i}"))
    return out


# ----------------------------------------------------------------------
# 正規化（與前端共用 normalize 向量）
# ----------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", SHARED["normalize"])
def test_norm_shared_vectors(raw, expected):
    assert sup.norm(raw) == expected


# ----------------------------------------------------------------------
# 真實頁面解析
# ----------------------------------------------------------------------
def test_real_list_pages_parse():
    p1 = sup.parse_list_page(read_fixture("list_s3_p1.html"), "s3")
    assert len(p1.rows) == 13 and p1.current == 1 and p1.has_next
    assert p1.rows[0].signature() == ("1150671", "2026/10/21", "易安穩膜衣錠 5/160 毫克",
                                      "Exforge film-coated tablet 5/160mg")
    p11 = sup.parse_list_page(read_fixture("list_s3_p11.html"), "s3")
    assert p11.current == 11 and 9 in p11.pages and p11.has_next   # `...` 跳組
    last = sup.parse_list_page(read_fixture("list_s3_p19.html"), "s3")
    assert last.current == 19 and not last.has_next and len(last.rows) == 10
    empty = sup.parse_list_page(read_fixture("list_s4_empty.html"), "s4")
    assert empty.empty and empty.rows == [] and empty.current is None


@pytest.mark.parametrize("name,category", [
    ("redirect_home.html", "s3"),     # s=1 跳轉回首頁
    ("list_s6_p1.html", "s3"),        # 公開徵求中，不是 s3
    ("list_s3_p1.html", "s2"),        # 類別錯置
])
def test_wrong_page_identity_is_error(name, category):
    with pytest.raises(sup.ScrapeError):
        sup.parse_list_page(read_fixture(name), category)


def real_row(name_part):
    p1 = sup.parse_list_page(read_fixture("list_s3_p1.html"), "s3")
    return next(r for r in p1.rows if name_part in r.name_zh)


def test_a1_melphalan_takes_newest_history_row():
    rec = sup.validate_detail(sup.parse_detail(read_fixture("detail_s3_melphalan.html")),
                              real_row("摩法爾"), "s3", TODAY)
    assert rec["公告更新時間"] == "2026/08/24"
    assert rec["供應狀態"].startswith("1.凱沛爾公司表示，因生產問題，無法預計恢復正常供應時程。\r\n2.")
    assert "預計115年8月底恢復供應" not in rec["供應狀態"]   # 04/30 那一列是舊版


# 2026-10-26 官網易安穩詳情頁「評估結果說明」逐字（含 6 個替代藥，任何一項被截短、錯置都要失敗）
EXFORGE_TEXT = "\r\n".join([
    "1.台灣諾華股份有限公司表示，因供應問題目前控貨中，10月初有輸入供應，後續將持續輸入。",
    "2.建議使用同成分同劑型同含量之藥品替代，如：",
    "◎壓立平膜衣錠5/160毫克 Valsoon F.C. Tablets 5/160mg(衛部藥製字第059836號) (訂購請洽生達化學製藥股份有限公司二廠)",
    "◎安普新膜衣錠5/160毫克 Exfopine Film-Coated Tablet 5/160mg (衛部藥製字第059821號) (訂購請洽永信藥品工業股份有限公司)",
    "◎安沛穩膜衣錠5/160毫克 Amvlo Film-Coated Tablets 5/160mg (衛部藥製字第060457號)(訂購請洽永勝藥品工業股份有限公司)",
    "◎易德壓悅膜衣錠5/160毫克(衛部藥製字第059771號)(訂購請美商亞培股份有限公司台灣分公司)",
    "◎安壓雙好膜衣錠5/160毫克 Estengy F.C. Tablets 5/160mg(衛部藥製字第059643號) (訂購請洽中國化學製藥股份有限公司新豐工廠)",
    "◎道脈樂5/160毫克膜衣錠 Dafiro 5/160mg Film-Coated Tablets(衛署藥輸字第025877號) (訂購請洽裕利股份有限公司)",
])


def test_a1_full_text_keeps_every_alternative():
    rec = sup.validate_detail(sup.parse_detail(read_fixture("detail_s3_exforge.html")),
                              real_row("易安穩"), "s3", TODAY)
    assert rec["供應狀態"] == EXFORGE_TEXT


def test_a7_record_format_matches_opendata():
    # 2026-10-26 主檔 104 的 COSOPIN 列（逐字）
    expected_text = (
        "1.井田國際醫藥廠股份有限公司表示，因生產問題，目前該藥品暫停出貨，恢復供應時程未知。\r\n"
        "2.建議使用同成分同劑型同含量之藥品替代，如：\r\n"
        "◎嗽隨康錠 SAUSCON TABLETS (衛署藥製字第014277號) (訂購請洽溫士頓醫藥股份有限公司)\r\n"
        "◎可待平錠 Codepine Tablets (衛署藥製字第050090號) (訂購請洽生達化學製藥股份有限公司)\r\n"
        "◎\"華興\" 安咳停錠 Ancopin Tablets \"H.S.\" (衛署藥製字第049089號) (訂購請洽華興化學製藥廠股份有限公司)"
    )
    rec = sup.validate_detail(sup.parse_detail(read_fixture("detail_s3_cosopin.html")),
                              real_row("可嗽平"), "s3", TODAY)
    assert rec["中文品名"] == '"井田"可嗽平錠\nCOSOPIN TABLETS "CHINTENG"'
    assert rec["許可證字號"] == "衛署藥製字第040794號"
    assert sup.norm(rec["供應狀態"]) == sup.norm(expected_text)
    vep = sup.validate_detail(sup.parse_detail(read_fixture("detail_s3_vepesid.html")),
                              real_row("滅必治"), "s3", TODAY)
    assert vep["中文品名"] == "滅必治軟膠囊50毫克\nVEPESID CAPSULES 50MG"   # 與主檔 05/07 版同構


def test_a7_name_without_english_has_no_newline():
    row = sup.ListRow("2026/10/01", "只有中文", "", "x", "1000001", "t$lbtnProductNameC")
    detail = sup.parse_detail(detail_html("1000001", "只有中文", "", "衛署藥製字第000001號",
                                          [("2026/10/01", "說明")]))
    assert sup.validate_detail(detail, row, "s3", TODAY)["中文品名"] == "只有中文"


# ----------------------------------------------------------------------
# A1／A4：詳情驗證反例
# ----------------------------------------------------------------------
ROW = sup.ListRow("2026/10/07", "測試藥", "TEST", "x", "1150570", "t$lbtnProductNameC")


@pytest.mark.parametrize("case,zh,license_no,history,why", [
    ("1150571", "測試藥", "衛署藥製字第000001號", [("2026/10/07", "x")], "相鄰案件"),
    ("1150570", "別的藥", "衛署藥製字第000001號", [("2026/10/07", "x")], "品名不符"),
    ("1150570", "測試藥", "衛署藥製字第000001號", [("2026/10/26", "新"), ("2026/10/07", "舊")],
     "列表抓完後網站已更新"),
    ("1150570", "測試藥", "衛署藥製字第000001號", [("2026/10/07", "甲"), ("2026/10/07", "乙")],
     "同日期多列內容不同"),
    ("1150570", "測試藥", "藥字第1號", [("2026/10/07", "x")], "證號格式錯"),
    ("1150570", "測試藥", "衛署藥製字第號", [("2026/10/07", "x")], "證號缺數字"),
    ("1150570", "測試藥", "衛署藥製字第000001號", [], "沒有歷次表"),
    ("1150570", "測試藥", "衛署藥製字第000001號", [("2026/10/07", "  ")], "說明為空"),
    ("1150570", "測試藥", "衛署藥製字第000001號", [("2026/02/30", "x")], "日期無效"),
])
def test_a1_a4_detail_violations(case, zh, license_no, history, why):
    detail = sup.parse_detail(detail_html(case, zh, "TEST", license_no, history))
    with pytest.raises(sup.ScrapeError):
        sup.validate_detail(detail, ROW, "s3", TODAY)


def test_empty_license_is_excluded_not_error():
    detail = sup.parse_detail(detail_html("1150570", "測試藥", "TEST", "  ", [("2026/10/07", "x")]))
    assert sup.validate_detail(detail, ROW, "s3", TODAY) is None


def test_missing_license_field_is_error():
    detail = sup.parse_detail(detail_html("1150570", "測試藥", "TEST", "", [("2026/10/07", "x")])
                              .replace('id="ContentPlaceHolder1_lblLicense"', 'id="other"'))
    with pytest.raises(sup.ScrapeError):
        sup.validate_detail(detail, ROW, "s3", TODAY)


def test_empty_license_rows_reported_and_not_added(tmp_path):
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": [drug("1091713", "2025/07/22", "雙硫代丁二酸注射劑", "TECHNE DMSA KIT",
                                 license_no=""),
                            drug("1091711", "2021/02/23", "植物酸鹽注射劑", "TECHNE PHYTATE KIT",
                                 license_no="")],
                     "s4": [], "s2": []})
    code, out = run_once(tmp_path, site, main_path)
    s3 = out["categories"]["s3"]
    assert code == 0 and s3["additions"] == []
    assert [e["_案件編號"] for e in s3["excluded_no_license"]] == ["1091713", "1091711"]


def test_a1_same_day_identical_rows_are_one_version():
    detail = sup.parse_detail(detail_html("1150570", "測試藥", "TEST", "衛署藥製字第000001號",
                                          [("2026/10/07", "同內容"), ("2026/10/07", "同內容")]))
    assert sup.validate_detail(detail, ROW, "s3", TODAY)["供應狀態"] == "同內容"


def test_r5_same_day_rows_differing_only_in_line_breaks_conflict():
    """R5：規格要求「內容完全相同」；`藥A\\n藥B` 與 `藥A藥B` 正規化後相同，但不是同一版。"""
    detail = sup.parse_detail(detail_html("1150570", "測試藥", "TEST", "衛署藥製字第000001號",
                                          [("2026/10/07", "◎藥A\n◎藥B"), ("2026/10/07", "◎藥A◎藥B")]))
    with pytest.raises(sup.ScrapeError, match="同日期"):
        sup.validate_detail(detail, ROW, "s3", TODAY)


@pytest.mark.parametrize("inner,expected", [
    ("1.甲。\n<br/>2.乙。", "1.甲。\r\n2.乙。"),           # 現行寫法：原始換行＋<br/> 只算一次
    ("1.甲。<br/>2.乙。", "1.甲。\r\n2.乙。"),             # 只有 <br>：也要換行，不得黏在一起
    ("1.甲。\r\n<br/>2.乙。", "1.甲。\r\n2.乙。"),
    ("1.甲。\n<br/>\n<br/>2.乙。", "1.甲。\r\n\r\n2.乙。"),  # 空行保留
    ("  1.甲。   \n<br/>2.乙。  ", "1.甲。   \r\n2.乙。"),   # 只去整段頭尾空白，行尾不動
])
def test_r5_br_handling_and_outer_strip_only(inner, expected):
    html = detail_html("1150570", "測試藥", "TEST", "衛署藥製字第000001號", [("2026/10/07", "PLACEHOLDER")])
    html = html.replace("PLACEHOLDER", inner)   # 直接放 HTML，不經 esc
    detail = sup.parse_detail(html)
    assert sup.validate_detail(detail, ROW, "s3", TODAY)["供應狀態"] == expected


def test_a4_future_date_rejected_but_tomorrow_allowed():
    future = sup.ListRow("2026/10/28", "測試藥", "TEST", "x", "1150570", "t$lbtnProductNameC")
    detail = sup.parse_detail(detail_html("1150570", "測試藥", "TEST", "衛署藥製字第000001號",
                                          [("2026/10/28", "x")]))
    with pytest.raises(sup.ScrapeError):
        sup.validate_detail(detail, future, "s3", TODAY)
    tomorrow = sup.ListRow("2026/10/27", "測試藥", "TEST", "x", "1150570", "t$lbtnProductNameC")
    detail = sup.parse_detail(detail_html("1150570", "測試藥", "TEST", "衛署藥製字第000001號",
                                          [("2026/10/27", "x")]))
    assert sup.validate_detail(detail, tomorrow, "s3", TODAY)


def test_radiopharm_license_format_accepted():
    assert sup.LICENSE_PATTERN.match("衛署藥輸字第R00049號")
    assert sup.LICENSE_PATTERN.match("內衛藥製字第004928號")
    assert sup.LICENSE_PATTERN.match("衛部罕菌疫輸字第000001號")


# ----------------------------------------------------------------------
# R7：真正的 DsmsClient（假 session，不連網）
# ----------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status, url, body="<html>ok</html>"):
        self.status_code = status
        self.url = url
        self.content = body.encode("utf-8")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("get", url, kw))
        return self.response

    def post(self, url, **kw):
        self.calls.append(("post", url, kw))
        return self.response


def client_with(response):
    return sup.DsmsClient(session=FakeSession(response), sleep=lambda _s: None)


LIST_OK = "https://dsms.fda.gov.tw/DrugList.aspx?s=3"
DETAIL_OK = "https://dsms.fda.gov.tw/DrugInfo.aspx?No=abc%3d&s=3&from=DrugList&r=1"


def test_r7_client_accepts_200_on_expected_pages():
    assert client_with(FakeResponse(200, LIST_OK)).get_list("s3") == "<html>ok</html>"
    assert client_with(FakeResponse(200, DETAIL_OK)).open_detail("s3", {"__VIEWSTATE": "v"}, "t")


@pytest.mark.parametrize("status,url,why", [
    (206, LIST_OK, "非 200 的 2xx"),
    (500, LIST_OK, "伺服器錯誤"),
    (200, "http://dsms.fda.gov.tw/DrugList.aspx?s=3", "降為 http"),
    (200, "https://evil.example/DrugList.aspx?s=3", "跳到別的主機"),
    (200, "https://dsms.fda.gov.tw:443/?r=1484819271", "跳回首頁（s=1 實測行為）"),
    (200, "https://dsms.fda.gov.tw/DrugList.aspx?s=2", "類別錯置"),
    (200, "https://dsms.fda.gov.tw/DrugInfo.aspx?s=3", "列表請求卻落在詳情頁"),
])
def test_r7_client_rejects_unexpected_responses(status, url, why):
    with pytest.raises(sup.ScrapeError):
        client_with(FakeResponse(status, url)).get_list("s3")


def test_r7_client_rejects_non_utf8_and_network_errors():
    bad = FakeResponse(200, LIST_OK)
    bad.content = b"\xff\xfe\xfa"
    with pytest.raises(sup.ScrapeError, match="請求失敗"):
        client_with(bad).get_list("s3")

    class Boom(FakeSession):
        def get(self, url, **kw):
            raise sup.requests.ConnectionError("TLS handshake failed")
    with pytest.raises(sup.ScrapeError, match="TLS"):
        sup.DsmsClient(session=Boom(None), sleep=lambda _s: None).get_list("s3")


def test_r7_client_postback_sends_hidden_fields_and_waits():
    waits = []
    session = FakeSession(FakeResponse(200, LIST_OK))
    sup.DsmsClient(session=session, sleep=waits.append).postback("s3", {"__VIEWSTATE": "v"},
                                                                  sup.GRID_TARGET, "Page$2")
    method, url, kw = session.calls[0]
    assert method == "post" and url == LIST_OK
    assert kw["data"] == {"__VIEWSTATE": "v", "__EVENTTARGET": sup.GRID_TARGET, "__EVENTARGUMENT": "Page$2"}
    assert kw["timeout"] == sup.REQUEST_TIMEOUT and waits == [sup.REQUEST_INTERVAL]


# ----------------------------------------------------------------------
# A2：完整掃描
# ----------------------------------------------------------------------
def scan(site, category="s3"):
    client = FakeClient(site)
    return sup.scan_category(client, category), client


def test_a2a_normal_three_pages():
    site = FakeSite({"s3": drugs_n(33)})
    pages, client = scan(site)
    assert [n for _, n in client.requests] == [1, 2, 3]
    assert [len(p.rows) for p, _ in pages] == [13, 13, 7]


def test_a2b_middle_page_short_is_error():
    site = FakeSite({"s3": drugs_n(33)})
    site.overrides[("s3", 2)] = list_html("s3", [
        {"date": d["date"], "zh": d["zh"], "case": d["case"]} for d in drugs_n(33)[13:25]
    ], current=2, total=3)
    with pytest.raises(sup.ScrapeError, match="非末頁"):
        scan(site)


def test_a2c_repeated_page_is_error():
    site = FakeSite({"s3": drugs_n(26)})
    site.overrides[("s3", 2)] = list_html("s3", [
        {"date": d["date"], "zh": d["zh"], "case": d["case"]} for d in drugs_n(26)[:13]
    ], current=2, total=2)
    with pytest.raises(sup.ScrapeError, match="重複"):
        scan(site)


def test_a2d_dates_increasing_is_error():
    rows = drugs_n(5)
    rows[0], rows[4] = rows[4], rows[0]
    rows[0]["date"], rows[4]["date"] = "2026/01/01", "2026/12/01"
    with pytest.raises(sup.ScrapeError, match="排序"):
        scan(FakeSite({"s3": rows}))


def test_a2e_page_40_still_has_next_is_error():
    with pytest.raises(sup.ScrapeError, match="上限"):
        scan(FakeSite({"s3": drugs_n(41 * 13)}))


def test_a2f_exactly_40_pages_ok():
    pages, _ = scan(FakeSite({"s3": drugs_n(40 * 13)}))
    assert len(pages) == 40


def test_a2g_full_page_without_pager_is_error():
    site = FakeSite({"s3": drugs_n(30)})
    site.overrides[("s3", 2)] = list_html("s3", [
        {"date": d["date"], "zh": d["zh"], "case": d["case"]} for d in drugs_n(30)[13:26]
    ])  # 滿 13 筆但沒有分頁列
    with pytest.raises(sup.ScrapeError, match="分頁列"):
        scan(site)


def test_a2g_wrong_page_marker_is_error():
    site = FakeSite({"s3": drugs_n(30)})
    site.overrides[("s3", 2)] = list_html("s3", [
        {"date": d["date"], "zh": d["zh"], "case": d["case"]} for d in drugs_n(30)[13:26]
    ], current=3, total=3)
    with pytest.raises(sup.ScrapeError, match="頁碼"):
        scan(site)


def test_a2h_real_pager_group_jump():
    # 第 10 頁的分頁列只到 11（`...` 指向 11），仍判定有下一頁
    p10 = sup.parse_list_page(read_fixture("list_s3_p10.html"), "s3")
    assert p10.current == 10 and p10.has_next


# ----------------------------------------------------------------------
# A3／A5：破損列與空集
# ----------------------------------------------------------------------
def test_a3_one_broken_row_fails_category_only(tmp_path):
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": drugs_n(13), "s4": [], "s2": [drug("3000001", "2026/09/01", "恢復藥")]})
    code, first = run_once(tmp_path, site, main_path)
    assert code == 0
    broken = list_html("s3", [], current=None).replace(
        '<tr class="grvHeader"><th>更新日期</th></tr>',
        '<tr class="grvHeader"><th>更新日期</th></tr><tr class="grvRow"><td>壞</td></tr>')
    site.overrides[("s3", 1)] = broken
    later = datetime(2026, 10, 27, 9, 10, tzinfo=sup.TAIPEI_TZ)
    code, second = run_once(tmp_path, site, main_path, now=later)
    assert code == 2
    s3, s2 = second["categories"]["s3"], second["categories"]["s2"]
    assert s3["state"] == "error"
    assert s3["additions"] == first["categories"]["s3"]["additions"]
    assert s3["last_success_at"] == first["categories"]["s3"]["last_success_at"]
    assert s2["state"] == "ok" and s2["last_success_at"] > first["categories"]["s2"]["last_success_at"]


@pytest.mark.parametrize("html", [
    "",                                                     # 200 但空白 body
    read_fixture("redirect_home.html"),                     # 首頁
    "<html><body><h1>系統錯誤</h1></body></html>",            # 錯誤頁
])
def test_a5_not_a_legit_empty_state(html):
    with pytest.raises(sup.ScrapeError):
        sup.parse_list_page(html, "s4")


@pytest.mark.parametrize("text", ["系統維護中", "資料讀取失敗", "", "尚無資料（維護中）"])
def test_r6_empty_node_with_other_text_is_error(text):
    html = list_html("s4", [], empty=True).replace(">尚無資料<", f">{text}<")
    with pytest.raises(sup.ScrapeError, match="尚無資料"):
        sup.parse_list_page(html, "s4")


def test_r6_maintenance_text_does_not_hide_main_rows(tmp_path):
    """R6 流程級：空狀態被改成維護訊息時，主檔只有 2 筆（低於熔斷上限）也不得被隱藏。"""
    rows = [opendata_row(str(i), "2026/09/01", f"無替代藥{i}") for i in range(2)]
    main_path = main_file(tmp_path, {"54505_no_alternative": rows})
    site = FakeSite({"s3": [], "s4": [], "s2": []})
    site.overrides[("s4", 1)] = list_html("s4", [], empty=True).replace(">尚無資料<", ">系統維護中<")
    code, out = run_once(tmp_path, site, main_path)
    s4 = out["categories"]["s4"]
    assert code == 2 and s4["state"] == "error" and s4["supersedes"] == []


def test_a5_empty_state_with_rows_is_error():
    html = list_html("s4", [{"date": "2026/10/01", "zh": "藥", "case": "1"}]).replace(
        "</table>", '<tr><td><span id="ContentPlaceHolder1_grvDrug_lbEmpty">尚無資料</span></td></tr></table>')
    with pytest.raises(sup.ScrapeError, match="同時出現"):
        sup.parse_list_page(html, "s4")


def test_a5_legit_empty_with_nonempty_main_hits_cap(tmp_path):
    rows = [opendata_row(str(i), "2026/09/01", f"無替代藥{i}") for i in range(5)]
    main_path = main_file(tmp_path, {"54505_no_alternative": rows})
    code, out = run_once(tmp_path, FakeSite({"s3": [], "s4": [], "s2": []}), main_path)
    assert out["categories"]["s4"]["state"] == "error"
    assert "熔斷" in out["categories"]["s4"]["error"]


# ----------------------------------------------------------------------
# A6：差異計算（共用情境＋熔斷邊界）
# ----------------------------------------------------------------------
def compute_case(case):
    """以純函式重現 process_category 的差異計算（不經網路）。"""
    category = case["category"]
    main_items = [(sup.main_unit(r, category), r) for r in case["main"]]
    if sup.CATEGORIES[category]["compare_content"]:
        site_items = [(sup.record_unit(r, category), r) for r in case["site"]]
    else:
        site_items = [((sup.norm(r["中文品名"].split("\n")[0]), r["公告更新時間"]), r) for r in case["site"]]
    added, removed = sup.diff_units(main_items, site_items, category)
    return added, [sup.supersede_entry(r, category) for r in removed]


@pytest.mark.parametrize("case", SHARED["cases"], ids=[c["name"] for c in SHARED["cases"]])
def test_a6_shared_cases(case):
    if case["expected"]["error"]:
        with pytest.raises(sup.ScrapeError):
            compute_case(case)
        return
    added, supersedes = compute_case(case)
    assert [r["編號"] for r in added] == case["expected"]["additions"]
    assert supersedes == case["expected"]["supersedes"]


@pytest.mark.parametrize("case", [c for c in SHARED["cases"] if not c["expected"]["error"]],
                         ids=lambda c: c["name"])
def test_a6_order_independent(case):
    shuffled = dict(case, main=random.Random(7).sample(case["main"], len(case["main"])),
                    site=random.Random(11).sample(case["site"], len(case["site"])))
    added, supersedes = compute_case(shuffled)
    assert sorted(r["編號"] for r in added) == sorted(case["expected"]["additions"])
    key = lambda e: json.dumps(e, ensure_ascii=False, sort_keys=True)
    assert sorted(supersedes, key=key) == sorted(case["expected"]["supersedes"], key=key)


@pytest.mark.parametrize("n_main,n_removed,ok", [
    (238, 4, True), (238, 5, False), (100, 3, True), (100, 4, False),
    (149, 3, True), (200, 4, True), (200, 5, False), (0, 0, True),
])
def test_a6_cap_boundaries(n_main, n_removed, ok):
    entries = [{}] * n_removed
    rows = [{}] * n_main
    if ok:
        sup.check_cap(entries, rows, "s3")
    else:
        with pytest.raises(sup.ScrapeError, match="熔斷"):
            sup.check_cap(entries, rows, "s3")


# ----------------------------------------------------------------------
# A8／A9：主檔不可用、原子寫入
# ----------------------------------------------------------------------
FULL_DATASETS = {"54504_with_alternative": [], "54505_no_alternative": [], "54506_resolved": []}


@pytest.mark.parametrize("content", [
    None, "{not json", json.dumps({"datasets": {}}),
    json.dumps({"last_updated": "2026-10-23 04:53:03",
                "datasets": {"54504_with_alternative": [], "54505_no_alternative": []}}),
    json.dumps({"datasets": FULL_DATASETS}),                                   # R1：缺 last_updated
    json.dumps({"last_updated": "2026/10/23", "datasets": FULL_DATASETS}),     # R1：格式錯
    json.dumps({"last_updated": 20261023, "datasets": FULL_DATASETS}),         # R1：型別錯
])
def test_a8_main_unusable_aborts_without_touching_output(tmp_path, content):
    main_path = tmp_path / "supply_status_latest.json"
    if content is not None:
        main_path.write_text(content, encoding="utf-8")
    out = tmp_path / "supply_supplement.json"
    out.write_bytes(b'{"schema": 1, "old": true}\n')
    with pytest.raises(sup.MainFileError):
        sup.run(main_path=str(main_path), output_path=str(out), client=FakeClient(FakeSite({})), now=NOW)
    assert out.read_bytes() == b'{"schema": 1, "old": true}\n'


def test_a9_atomic_write_failure_keeps_old_file(tmp_path, monkeypatch):
    out = tmp_path / "supply_supplement.json"
    out.write_bytes(b"OLD")

    def broken_dump(obj, f, **kwargs):
        f.write('{"partial": ')
        raise RuntimeError("disk full")

    monkeypatch.setattr(sup.json, "dump", broken_dump)
    with pytest.raises(RuntimeError):
        sup.write_atomic(str(out), {"x": 1})
    assert out.read_bytes() == b"OLD"
    assert [p.name for p in tmp_path.iterdir()] == ["supply_supplement.json"]


def test_a9_replace_failure_keeps_old_file(tmp_path, monkeypatch):
    out = tmp_path / "supply_supplement.json"
    out.write_bytes(b"OLD")
    monkeypatch.setattr(sup.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError):
        sup.write_atomic(str(out), {"x": 1})
    assert out.read_bytes() == b"OLD"


def test_a9_success_is_complete_valid_snapshot(tmp_path):
    main_path = main_file(tmp_path)
    code, out = run_once(tmp_path, FakeSite({"s3": [], "s4": [], "s2": []}), main_path)
    assert code == 0 and out["schema"] == 1 and set(out["categories"]) == {"s2", "s3", "s4"}
    assert all(c["success_run_id"] == out["run_id"] for c in out["categories"].values())


# ----------------------------------------------------------------------
# A10：跨次序列
# ----------------------------------------------------------------------
def test_a10_lifecycle(tmp_path):
    x = drug("1150900", "2026/10/20", "X藥", license_no="衛署藥輸字第000900號", text="X缺藥")
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": [x], "s4": [], "s2": []})

    # ① O 沒有 X；s3 有 X → s3 additions 含 X
    code, r1 = run_once(tmp_path, site, main_path)
    assert [a["_案件編號"] for a in r1["categories"]["s3"]["additions"]] == ["1150900"]

    # ② s3 失敗 → 沿用 ①，last_success_at 停在 ①
    site.overrides[("s3", 1)] = "<html></html>"
    t2 = datetime(2026, 10, 27, 9, 10, tzinfo=sup.TAIPEI_TZ)
    code, r2 = run_once(tmp_path, site, main_path, now=t2)
    s3 = r2["categories"]["s3"]
    assert code == 2 and s3["state"] == "error"
    assert s3["additions"] == r1["categories"]["s3"]["additions"]
    assert s3["last_success_at"] == r1["categories"]["s3"]["last_success_at"]
    assert s3["success_run_id"] != r2["run_id"]

    # ③ X 從 s3 移到 s2，O 仍沒有 X → s3 additions 消失（不是 supersedes），s2 additions 有完整 record
    del site.overrides[("s3", 1)]
    x2 = drug("1150900", "2026/10/25", "X藥", license_no="衛署藥輸字第000900號", text="X已恢復")
    site.categories = {"s3": [], "s4": [], "s2": [x2]}
    t3 = datetime(2026, 10, 28, 9, 10, tzinfo=sup.TAIPEI_TZ)
    code, r3 = run_once(tmp_path, site, main_path, now=t3)
    assert r3["categories"]["s3"]["additions"] == [] and r3["categories"]["s3"]["supersedes"] == []
    [rec] = r3["categories"]["s2"]["additions"]
    assert rec["許可證字號"] == "衛署藥輸字第000900號" and rec["供應狀態"] == "X已恢復"

    # ④ O 補上 X（106），其他也一致 → 三類差異歸零
    main_path = main_file(tmp_path, {"54506_resolved": [
        opendata_row("1", "2026/10/25", "X藥", license_no="衛署藥輸字第000900號", text="X已恢復")]})
    code, r4 = run_once(tmp_path, site, main_path, now=t3)
    assert code == 0
    assert all(not c["additions"] and not c["supersedes"] for c in r4["categories"].values())


def test_a10_source_ok_destination_failed(tmp_path):
    # ⑤ O 有 W 在 104；網站把 W 移到 s4；s3 成功、s4 失敗 → s3 supersedes W，但 run 不滿足 D10
    main_path = main_file(tmp_path, {"54504_with_alternative": [opendata_row("1", "2026/09/01", "W藥")]})
    site = FakeSite({"s3": [], "s4": [drug("1150901", "2026/10/22", "W藥")], "s2": []})
    site.overrides[("s4", 1)] = "<html>壞</html>"
    code, out = run_once(tmp_path, site, main_path)
    assert code == 2
    assert out["categories"]["s3"]["state"] == "ok" and len(out["categories"]["s3"]["supersedes"]) == 1
    assert out["categories"]["s4"]["state"] == "error"
    assert out["categories"]["s4"]["success_run_id"] is None   # 前端據此不得隱藏 W（B2／B8）


def test_a10_first_run_failure_has_no_results(tmp_path):
    # ⑦ 首次執行就失敗 → error、沒有任何結果
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": [], "s4": [], "s2": []})
    site.overrides[("s2", 1)] = "<html></html>"
    code, out = run_once(tmp_path, site, main_path)
    s2 = out["categories"]["s2"]
    assert s2["state"] == "error" and s2["additions"] == [] and s2["supersedes"] == []
    assert s2["last_success_at"] is None and s2["base"] is None


def _valid_previous(tmp_path):
    """先跑一次成功，取得合法前檔（s2 有一筆 addition）。"""
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": [], "s4": [], "s2": [drug("1150700", "2026/10/20", "新恢復藥",
                                                     license_no="衛部藥輸字第000061號")]})
    _, out = run_once(tmp_path, site, main_path)
    return main_path, out


@pytest.mark.parametrize("corrupt", [
    lambda d: d["categories"]["s2"]["additions"].append(None),
    lambda d: d["categories"]["s2"]["additions"][0].update(公告更新時間="2099/13/01"),
    lambda d: d["categories"]["s2"]["additions"][0].update(編號="wrong-id"),
    lambda d: d["categories"]["s2"]["additions"][0].update(_案件編號="not-a-number"),
    lambda d: d["categories"]["s2"]["additions"][0].update(許可證字號="藥字第1號"),
    lambda d: d["categories"]["s2"].update(base=None),
    lambda d: d["categories"]["s2"].update(dataset="54504_with_alternative"),
    lambda d: d["categories"]["s3"]["supersedes"].append({"品名鍵": "x", "公告更新時間": "2026/01/01",
                                                         "許可證字號": "y", "指紋": None}),
    lambda d: d["categories"].pop("s4"),
], ids=["null 筆", "日期無效", "編號不對應", "案件編號非數字", "證號格式錯", "缺 base",
        "dataset 錯置", "s3 指紋為 null", "缺類別"])
def test_r3_parseable_but_invalid_previous_is_discarded(tmp_path, corrupt):
    main_path, good = _valid_previous(tmp_path)
    corrupt(good)
    (tmp_path / "supply_supplement.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    site = FakeSite({"s3": [drug("1150671", "2026/10/21", "新缺藥")], "s4": [], "s2": []})
    site.overrides[("s2", 1)] = "<html></html>"   # s2 本次失敗 → 若沿用就會沿用到損壞內容
    code, out = run_once(tmp_path, site, main_path)
    s2 = out["categories"]["s2"]
    assert s2["state"] == "error" and s2["additions"] == [] and s2["last_success_at"] is None
    # D4 故障隔離：s3 本次的新缺藥照常發布，整份輸出仍合法
    assert [a["_案件編號"] for a in out["categories"]["s3"]["additions"]] == ["1150671"]
    assert sup.output_problems(out) == []


def test_r3_valid_previous_is_carried_over_completely(tmp_path):
    """A3／A10 補強：沿用時 base、success_run_id、supersedes 等全部欄位等於前檔。"""
    main_path, good = _valid_previous(tmp_path)
    site = FakeSite({"s3": [], "s4": [], "s2": []})
    site.overrides[("s2", 1)] = "<html></html>"
    later = datetime(2026, 10, 27, 9, 10, tzinfo=sup.TAIPEI_TZ)
    _, out = run_once(tmp_path, site, main_path, now=later)
    s2, prev = out["categories"]["s2"], good["categories"]["s2"]
    for key in ("last_success_at", "success_run_id", "base", "scanned", "additions", "supersedes",
                "excluded_no_license"):
        assert s2[key] == prev[key], key


def test_r3_invalid_output_is_never_written(tmp_path, monkeypatch):
    main_path = main_file(tmp_path)
    out = tmp_path / "supply_supplement.json"
    out.write_bytes(b"OLD")
    monkeypatch.setattr(sup, "build_output", lambda *a, **k: {"schema": 1})
    with pytest.raises(RuntimeError, match="契約"):
        sup.run(main_path=main_path, output_path=str(out),
                client=FakeClient(FakeSite({"s3": [], "s4": [], "s2": []})), now=NOW)
    assert out.read_bytes() == b"OLD"


def test_a10_corrupt_previous_treated_as_first_run(tmp_path):
    main_path = main_file(tmp_path)
    (tmp_path / "supply_supplement.json").write_text("{broken", encoding="utf-8")
    site = FakeSite({"s3": [], "s4": [], "s2": []})
    site.overrides[("s3", 1)] = "<html></html>"
    code, out = run_once(tmp_path, site, main_path)
    assert out["categories"]["s3"]["last_success_at"] is None


def test_a6_unsupported_main_name_fails_category(tmp_path):
    bad = {"編號": "1", "公告更新時間": "2026/09/01", "中文品名": "沒有英文", "許可證字號": "衛署藥製字第000001號",
           "供應狀態": "x"}
    main_path = main_file(tmp_path, {"54504_with_alternative": [bad]})
    code, out = run_once(tmp_path, FakeSite({"s3": [], "s4": [], "s2": []}), main_path)
    assert out["categories"]["s3"]["state"] == "error"
    assert out["categories"]["s3"]["supersedes"] == []


# ----------------------------------------------------------------------
# A12：兩輪掃描
# ----------------------------------------------------------------------
def changing_site(change_on_calls):
    """第 change_on_calls 次觀測（s3 列表被讀的次數）時，少掉一筆。"""
    full = drugs_n(20)

    def drugs(call_no):
        return full[:-1] if call_no in change_on_calls else full
    return FakeSite({"s3": drugs, "s4": [], "s2": []})


def test_a12a_inconsistent_twice_fails_all(tmp_path):
    main_path = main_file(tmp_path)
    code, out = run_once(tmp_path, changing_site({2, 4}), main_path)
    assert code == 2
    assert all(c["state"] == "error" and "不一致" in c["error"] for c in out["categories"].values())


def test_a12c_retry_consistent_succeeds_with_retry_observation(tmp_path):
    main_path = main_file(tmp_path)
    code, out = run_once(tmp_path, changing_site({2}), main_path)   # 第 1 次觀測不一致，重試穩定
    assert code == 0
    assert out["categories"]["s3"]["scanned"]["rows"] == 20


@pytest.mark.parametrize("field", ["case", "date", "zh", "order"])
def test_a12d_any_field_difference_is_inconsistent(field):
    base = drugs_n(3)
    other = [dict(d) for d in base]
    if field == "case":
        other[1]["case"] = "9999999"
    elif field == "date":
        other[2]["date"] = "2026/09/01"   # 仍非遞增，只改日期
    elif field == "zh":
        other[1]["zh"] = "改名藥"
    else:
        other[1], other[2] = other[2], other[1]
    a = sup.scan_category(FakeClient(FakeSite({"s3": base})), "s3")
    b = sup.scan_category(FakeClient(FakeSite({"s3": other})), "s3")
    assert sup._signature(a) != sup._signature(b)


def test_a12e_consistent_passes_scan_twice(tmp_path):
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": drugs_n(5), "s4": [], "s2": []})
    client = FakeClient(site)
    sup.run(main_path=main_path, output_path=str(tmp_path / "o.json"), client=client, now=NOW)
    assert site.list_calls == 2   # 兩輪，沒有重試


# ----------------------------------------------------------------------
# 整合：真實結構的 s3 修訂（改日期）流程
# ----------------------------------------------------------------------
def test_revision_flow_end_to_end(tmp_path):
    main_path = main_file(tmp_path, {"54504_with_alternative": [
        opendata_row("1", "2026/05/07", "滅必治軟膠囊50毫克", "VEPESID CAPSULES 50MG",
                     "衛署藥輸字第020882號", "舊說明")]})
    site = FakeSite({"s3": [drug("1141284", "2026/10/16", "滅必治軟膠囊50毫克", "VEPESID CAPSULES 50MG",
                                 "衛署藥輸字第020882號", "新說明")], "s4": [], "s2": []})
    code, out = run_once(tmp_path, site, main_path)
    s3 = out["categories"]["s3"]
    assert code == 0
    assert [a["公告更新時間"] for a in s3["additions"]] == ["2026/10/16"]
    assert s3["supersedes"] == [{"品名鍵": "滅必治軟膠囊50毫克", "公告更新時間": "2026/05/07",
                                 "許可證字號": "衛署藥輸字第020882號", "指紋": "舊說明"}]
    assert s3["base"] == {"last_updated": "2026-10-23 04:53:03", "upstream_max_date": "2026/10/07"}


# ----------------------------------------------------------------------
# 覆審補強（verdict-supplement.md T2／T3／S-A3／A6／A7／A8／A10）
# ----------------------------------------------------------------------
def test_a4_fourth_detail_bad_reverts_whole_category(tmp_path):
    """規格 A4：前 3 筆詳情正常、第 4 筆壞 → 整類 error，結果與成功時間都回到前檔。"""
    main_path = main_file(tmp_path)
    drugs = [drug(str(1150800 + i), "2026/10/2%d" % (5 - i), f"甲藥{i}") for i in range(5)]
    site = FakeSite({"s3": drugs, "s4": [], "s2": []})
    _, first = run_once(tmp_path, site, main_path)
    assert len(first["categories"]["s3"]["additions"]) == 5
    site.detail_overrides["1150803"] = detail_html("1150803", "甲藥3", "EN", "藥字第1號",
                                                   [("2026/10/22", "x")])
    later = datetime(2026, 10, 27, 9, 10, tzinfo=sup.TAIPEI_TZ)
    code, second = run_once(tmp_path, site, main_path, now=later)
    s3, prev = second["categories"]["s3"], first["categories"]["s3"]
    assert code == 2 and s3["state"] == "error" and "許可證字號無效" in s3["error"]
    for key in ("additions", "supersedes", "last_success_at", "success_run_id", "base"):
        assert s3[key] == prev[key], key


def test_a1_same_day_revision_end_to_end(tmp_path):
    """A1(b)：日期不變、只改文字，經詳情抓取的完整流程。"""
    main_path = main_file(tmp_path, {"54504_with_alternative": [
        opendata_row("1", "2026/10/07", "可嗽平錠", "COSOPIN", "衛署藥製字第040794號", "替代：◎甲藥")]})
    site = FakeSite({"s3": [drug("1150570", "2026/10/07", "可嗽平錠", "COSOPIN", "衛署藥製字第040794號",
                                 "替代：◎乙藥")], "s4": [], "s2": []})
    code, out = run_once(tmp_path, site, main_path)
    s3 = out["categories"]["s3"]
    assert code == 0
    assert [(a["公告更新時間"], a["供應狀態"]) for a in s3["additions"]] == [("2026/10/07", "替代：◎乙藥")]
    assert s3["supersedes"] == [{"品名鍵": "可嗽平錠", "公告更新時間": "2026/10/07",
                                 "許可證字號": "衛署藥製字第040794號", "指紋": "替代:◎甲藥"}]


def _page2(cases, current=2, total=3):
    # 日期落在第 1 頁之後、第 3 頁之前，確保失敗原因是本反例而不是日期排序
    rows = [{"date": "2026/09/20", "zh": f"背景藥{i}", "case": str(c)} for i, c in enumerate(cases)]
    return list_html("s3", rows, current=current, total=total) if current else list_html("s3", rows)


@pytest.mark.parametrize("override", [
    lambda: _page2(range(2000013, 2000025)),                 # 中間頁 12 筆
    lambda: _page2(range(2000000, 2000013)),                 # 重複頁（與第 1 頁同案件）
    lambda: _page2(range(2000013, 2000026), current=None),   # 滿 13 筆但沒有分頁列
], ids=["中間頁短少", "重複頁", "提早截斷"])
def test_a2_scan_errors_keep_previous_results(tmp_path, override):
    """T3：A2 的反例經完整流程，驗證該類沿用前檔、其他類照常。"""
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": drugs_n(33), "s4": [], "s2": []})
    _, first = run_once(tmp_path, site, main_path)
    site.overrides[("s3", 2)] = override()
    later = datetime(2026, 10, 27, 9, 10, tzinfo=sup.TAIPEI_TZ)
    code, second = run_once(tmp_path, site, main_path, now=later)
    assert code == 2 and second["categories"]["s3"]["state"] == "error"
    assert second["categories"]["s3"]["additions"] == first["categories"]["s3"]["additions"]
    assert second["categories"]["s2"]["last_success_at"] == later.isoformat(timespec="seconds")


def test_a2h_pager_group_jump_end_to_end():
    """跨 10 頁一組的 `...` 跳組：實際請求到第 11 頁以後。"""
    pages, client = scan(FakeSite({"s3": drugs_n(12 * 13 + 4)}))
    assert [n for _, n in client.requests] == list(range(1, 14))
    assert len(pages) == 13


def test_a12b_cross_category_move_between_passes_fails_all(tmp_path):
    """A12(b)：每一輪時一筆公告在 s3／s4 之間移動（各類單獨看都合法）→ 重試仍不同 → 三類 error。"""
    x = drug("1150901", "2026/10/22", "移類藥")
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": lambda n: [x] if n % 2 else [],
                     "s4": lambda n: [] if n % 2 else [x], "s2": []})
    code, out = run_once(tmp_path, site, main_path)
    assert code == 2
    assert all(c["state"] == "error" and "不一致" in c["error"] for c in out["categories"].values())


def test_a12c_result_comes_only_from_retry_observation(tmp_path):
    """A12(c)：各次觀測內容可區別——第 1 次兩輪不同（A、B），重試兩輪都是 C，結果必須是 C。"""
    versions = {1: "A版", 2: "B版"}
    main_path = main_file(tmp_path)
    site = FakeSite({"s3": lambda n: [drug("1150902", "2026/10/22", versions.get(n, "C版"))],
                     "s4": [], "s2": []})
    code, out = run_once(tmp_path, site, main_path)
    assert code == 0 and site.list_calls == 4
    assert [a["中文品名"].split("\n")[0] for a in out["categories"]["s3"]["additions"]] == ["C版"]


def test_a6_main_name_with_two_newlines_fails_category(tmp_path):
    bad = opendata_row("1", "2026/09/01", "甲藥\n多一行", "EN")
    main_path = main_file(tmp_path, {"54504_with_alternative": [bad]})
    _, out = run_once(tmp_path, FakeSite({"s3": [], "s4": [], "s2": []}), main_path)
    assert out["categories"]["s3"]["state"] == "error" and "結構不支援" in out["categories"]["s3"]["error"]


@pytest.mark.parametrize("zh,en,expected", [
    ("\"井田\"可嗽平錠", "COSOPIN TABLETS \"CHINTENG\"", "\"井田\"可嗽平錠\nCOSOPIN TABLETS \"CHINTENG\""),
    ("「華興」安咳停錠", "Ancopin Tablets \"H.S.\"", "「華興」安咳停錠\nAncopin Tablets \"H.S.\""),
    ("易安穩膜衣錠 5/160 毫克", "Exforge 5/160mg", "易安穩膜衣錠 5/160 毫克\nExforge 5/160mg"),
    ("甲&乙注射劑", "A & B Injection", "甲&乙注射劑\nA & B Injection"),
    ("只有中文", "", "只有中文"),
])
def test_a7_name_formats(zh, en, expected):
    row = sup.ListRow("2026/10/01", zh, en, "x", "1000001", "t$lbtnProductNameC")
    detail = sup.parse_detail(detail_html("1000001", zh, en, "衛署藥製字第000001號", [("2026/10/01", "說明")]))
    assert sup.validate_detail(detail, row, "s3", TODAY)["中文品名"] == expected


def test_a8_cli_exits_1_when_main_unusable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)   # 沒有 public/data/supply_status_latest.json
    with pytest.raises(SystemExit) as exc:
        sup.main()
    assert exc.value.code == 1
    assert "主檔不可用" in capsys.readouterr().err
    assert not (tmp_path / "public").exists()


# ----------------------------------------------------------------------
# A10 跨端：Python 實際產出的快照交給前端測試（src/lib/supplement.test.ts）
# ----------------------------------------------------------------------
CROSS_FIXTURE = os.path.join(HERE, "fixtures", "cross_s2_error_carried.json")


def build_cross_snapshot(tmp_path):
    """s2 先成功產出 V 的恢復公告，再失敗而沿用；V 在主檔 104 仍是缺藥。"""
    v_main = opendata_row("1", "2026/10/01", "V藥", "EN", "衛署藥輸字第000777號", "缺藥中")
    main_path = main_file(tmp_path, {"54504_with_alternative": [v_main]})
    site = FakeSite({"s3": [drug("1150777", "2026/10/01", "V藥", "EN", "衛署藥輸字第000777號", "缺藥中")],
                     "s4": [],
                     "s2": [drug("1150778", "2026/10/20", "V藥", "EN", "衛署藥輸字第000777號", "已恢復")]})
    run_once(tmp_path, site, main_path, now=datetime(2026, 10, 26, 9, 0, tzinfo=sup.TAIPEI_TZ))
    site.overrides[("s2", 1)] = "<html></html>"
    _, out = run_once(tmp_path, site, main_path, now=datetime(2026, 10, 26, 10, 0, tzinfo=sup.TAIPEI_TZ))
    with open(main_path, encoding="utf-8") as f:
        main = json.load(f)
    # run_id 含亂數：換成固定值讓 fixture 可重現（保留「是不是同一次執行」的關係）
    later = out["run_id"]
    out["run_id"] = "RUN-LATER"
    for c in out["categories"].values():
        if c["success_run_id"] is not None:
            c["success_run_id"] = "RUN-LATER" if c["success_run_id"] == later else "RUN-EARLIER"
    return {"main": main, "supplement": out}


def test_a10_cross_end_fixture_is_current(tmp_path):
    snapshot = build_cross_snapshot(tmp_path)
    s2 = snapshot["supplement"]["categories"]["s2"]
    assert s2["state"] == "error" and len(s2["additions"]) == 1 and s2["success_run_id"] == "RUN-EARLIER"
    assert sup.output_problems(snapshot["supplement"]) == []
    with open(CROSS_FIXTURE, encoding="utf-8") as f:
        committed = json.load(f)
    assert committed == snapshot, "Python 產出變了：重新產生 fixture 並確認前端測試"
