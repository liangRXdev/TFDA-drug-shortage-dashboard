"""dsms 公告頁補抓（增量 S，規格見 .ai-review/plan-supplement.md r4）。

opendata 104／105／106 停更期間，以食藥署「西藥供應資訊」網站
（dsms.fda.gov.tw/DrugList.aspx?s=N）的完整列表快照，算出與主檔的差異：
- additions：網站有、主檔沒有（或 s3/s4 內容已變）的公告，附完整欄位
- supersedes：主檔有、但網站快照中已不存在（或 s3/s4 內容已變）的列

只寫 public/data/supply_supplement.json，**絕不**寫入 supply_status_latest.json（D1）：
每週 CI 以 opendata 全量覆寫主檔，併入的資料會被沖掉，並污染 frozen_runs。

設計原則：
- 按類別判定成敗（D4）：任一類失敗只影響該類，沿用前檔該類的上次成功結果。
- 寧可 error 不可猜（D7）：完整性守門任一條不成立、或同一比較單位在兩邊次數不同，
  一律該類 error，不任選一筆刪除。
- 兩輪掃描（D8）：掃描中網站有變動時，單輪快照可能是不同時間點拼起來的。
- 熔斷（D9）：supersedes 過多視為改版或命名規則變動，該類 error，不自動放寬。

為什麼不在 CI 跑：同機關的 consumer.fda.gov.tw 已證實封鎖境外 IP；dsms 的 CI 可達性
未驗證（D3）。由本機 scripts/update_supplement.py 每日排程呼叫。

exit 碼：0 = 三類皆 ok；2 = 部分類別 error（仍寫檔）；1 = 主檔不可用，未寫檔。

所有純邏輯皆抽為可 import 的函式，供 pytest 在無網路下以 fixture 測試。
"""
import os
import re
import sys
import json
import time
import secrets
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, date, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs

import requests

TAIPEI_TZ = timezone(timedelta(hours=8))

DSMS_HOST = "dsms.fda.gov.tw"
BASE_URL = f"https://{DSMS_HOST}/DrugList.aspx"
CATEGORIES = {
    "s3": {"s": 3, "dataset": "54504_with_alternative",
           "title": "建議使用替代藥品或其他建議", "compare_content": True},
    "s4": {"s": 4, "dataset": "54505_no_alternative",
           "title": "無替代藥品品項", "compare_content": True},
    "s2": {"s": 2, "dataset": "54506_resolved",
           "title": "已恢復供應藥品品項", "compare_content": False},
}
SCAN_ORDER = ("s3", "s4", "s2")

PAGE_SIZE = 13                 # 非末頁每頁筆數（2026-10-26 實測）
MAX_PAGES = 40                 # 翻頁上限；第 40 頁仍有下一頁 → error
REQUEST_INTERVAL = 0.5         # 秒；每個請求前固定間隔，降低對政府網站的負載
REQUEST_TIMEOUT = 30
CAP_MIN = 3                    # D9 熔斷：cap = max(CAP_MIN, floor(CAP_RATIO × |O|))
CAP_RATIO = 0.02
MAX_ATTEMPTS = 2               # 兩輪掃描不一致時，整次重試一次
FUTURE_TOLERANCE_DAYS = 1      # 日期不得晚於今天＋1 天（台灣時區）

GRID_TARGET = "ctl00$ContentPlaceHolder1$grvDrug"
GRID_ID = "ContentPlaceHolder1_grvDrug"
SCHEMA = 1

MAIN_PATH = os.path.join("public", "data", "supply_status_latest.json")
OUTPUT_PATH = os.path.join("public", "data", "supply_supplement.json")

DATE_PATTERN = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
# 字號允許英文字母前綴：放射性藥品為「字第R00049號」（主檔 14 筆）
LICENSE_PATTERN = re.compile(r"^(衛署|衛部|內衛)\S*字第[A-Z]?\d+號$")
CASE_PATTERN = re.compile(r"^\d+$")
POSTBACK_PATTERN = re.compile(r"__doPostBack\('([^']+)','([^']*)'\)")

# 比較用空白集合：明列而不用 \s，因為 Python 與 JS 的 \s 定義不同。
# 前端 src/lib/supplement.ts 的 WHITESPACE 必須與此逐字相同。
WHITESPACE = re.compile(
    "[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a"
    "\u2028\u2029\u202f\u205f\u3000\u200b\ufeff]"
)


class ScrapeError(Exception):
    """單一類別無法產出可信結果；該類 error，其他類照常。"""


class MainFileError(Exception):
    """主檔不可用：沒有比對基準，整批中止、不寫檔。"""


def norm(value):
    """比較用正規化：NFKC 後去除全部空白。只用於比較，不改寫顯示文字。"""
    return WHITESPACE.sub("", unicodedata.normalize("NFKC", value or ""))


def parse_date(value):
    """`YYYY/MM/DD` 且為真實曆日 → 原字串；否則 None。"""
    if not isinstance(value, str):
        return None
    m = DATE_PATTERN.match(value.strip())
    if not m:
        return None
    try:
        date(*(int(g) for g in m.groups()))
    except ValueError:
        return None
    return value.strip()


def check_date(value, today, what):
    """驗證日期有效且不在未來（容許 FUTURE_TOLERANCE_DAYS）；失敗 raise。"""
    parsed = parse_date(value)
    if parsed is None:
        raise ScrapeError(f"{what}：日期無效（{value!r}）")
    limit = (today + timedelta(days=FUTURE_TOLERANCE_DAYS)).strftime("%Y/%m/%d")
    if parsed > limit:
        raise ScrapeError(f"{what}：日期 {parsed} 晚於今天")
    return parsed


# ----------------------------------------------------------------------
# 最小 DOM：dsms 為 ASP.NET WebForms，欄位都有固定 element id，
# 以標準庫 html.parser 建樹即可（D12，不加 bs4）。
# ----------------------------------------------------------------------
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.children = []
        self.parent = parent


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.current))

    def handle_endtag(self, tag):
        # 容錯：往上找同名節點才關閉；找不到就忽略這個多餘的結束標籤
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse_html(text):
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


def iter_nodes(node):
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from iter_nodes(child)


def find_by_id(node, element_id):
    return next((n for n in iter_nodes(node) if n.attrs.get("id") == element_id), None)


BR_MARK = "\x00BR\x00"   # display_text 會把它轉成換行；只在詳情內文使用


def text_of(node, br=""):
    """節點內全部文字；`<br>` 以 br 取代（預設忽略，詳情內文傳 BR_MARK）。"""
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append(br)
        else:
            parts.append(text_of(child, br))
    return "".join(parts)


def child_elements(node, tag):
    return [c for c in node.children if isinstance(c, Node) and c.tag == tag]


def parse_hidden_fields(text):
    """ASP.NET postback 需要的 hidden fields（__VIEWSTATE 等）。"""
    root = parse_html(text)
    return {n.attrs["name"]: n.attrs.get("value", "")
            for n in iter_nodes(root)
            if n.tag == "input" and n.attrs.get("type") == "hidden" and n.attrs.get("name")}


# ----------------------------------------------------------------------
# 列表頁
# ----------------------------------------------------------------------
class ListRow:
    __slots__ = ("date", "name_zh", "name_en", "applicant", "case_no", "target")

    def __init__(self, date, name_zh, name_en, applicant, case_no, target):
        self.date = date
        self.name_zh = name_zh
        self.name_en = name_en
        self.applicant = applicant
        self.case_no = case_no
        self.target = target

    def signature(self):
        """兩輪掃描比對用（D8）：案件編號、日期、品名；順序由清單位置表達。"""
        return (self.case_no, self.date, self.name_zh, self.name_en)


class ListPage:
    __slots__ = ("rows", "current", "pages", "empty")

    def __init__(self, rows, current, pages, empty):
        self.rows = rows          # list[ListRow]
        self.current = current    # 分頁列的目前頁碼標記；沒有分頁列為 None
        self.pages = pages        # 分頁列中可點的頁碼（含 `...` 指向的頁）
        self.empty = empty        # 列表區顯示「尚無資料」

    @property
    def has_next(self):
        return self.current is not None and (self.current + 1) in self.pages


def _grid_rows(grid):
    """grid 的頂層 <tr>（略過分頁列內巢狀 table 的 <tr>）。"""
    rows = []
    for child in child_elements(grid, "tr"):
        rows.append(child)
    for section in child_elements(grid, "tbody") + child_elements(grid, "thead"):
        rows.extend(child_elements(section, "tr"))
    return rows


def _parse_pager(tr):
    """分頁列 → (目前頁碼, 可點頁碼集合)；不是分頁列回 None。"""
    links = [n for n in iter_nodes(tr) if n.tag == "a"]
    pages = set()
    for a in links:
        m = POSTBACK_PATTERN.search(a.attrs.get("href", ""))
        if not m or m.group(1) != GRID_TARGET or not m.group(2).startswith("Page$"):
            return None
        number = m.group(2)[len("Page$"):]
        if not number.isdigit():
            return None
        pages.add(int(number))
    spans = [text_of(n).strip() for n in iter_nodes(tr) if n.tag == "span"]
    if len(spans) != 1 or not spans[0].isdigit():
        return None
    return int(spans[0]), pages


def _parse_list_row(tr, category):
    tds = child_elements(tr, "td")
    if len(tds) != 5:
        raise ScrapeError(f"{category}：資料列欄位數 {len(tds)}，預期 5（疑似改版）")
    anchor = next((n for n in iter_nodes(tds[1]) if n.tag == "a"), None)
    m = POSTBACK_PATTERN.search(anchor.attrs.get("href", "")) if anchor else None
    if not m or not m.group(1).endswith("$lbtnProductNameC"):
        raise ScrapeError(f"{category}：資料列缺詳情連結（疑似改版）")
    row = ListRow(
        date=text_of(tds[0]).strip(),
        name_zh=text_of(tds[1]).strip(),
        name_en=text_of(tds[2]).strip(),
        applicant=text_of(tds[3]).strip(),
        case_no=text_of(tds[4]).strip(),
        target=m.group(1),
    )
    if parse_date(row.date) is None or not row.name_zh or not CASE_PATTERN.match(row.case_no):
        raise ScrapeError(f"{category}：資料列內容無效（{row.case_no!r} {row.date!r}）")
    return row


def parse_list_page(text, category):
    """解析一頁列表；頁面身分、列結構任一不符即 raise ScrapeError。"""
    root = parse_html(text)
    title = find_by_id(root, "ContentPlaceHolder1_lblTitle")
    if title is None or text_of(title).strip() != CATEGORIES[category]["title"]:
        raise ScrapeError(f"{category}：頁面標題不符（非預期頁面）")
    grid = find_by_id(root, GRID_ID)
    if grid is None:
        raise ScrapeError(f"{category}：找不到列表（疑似改版）")
    empty_nodes = [n for n in iter_nodes(grid) if n.attrs.get("id") == GRID_ID + "_lbEmpty"]
    # R6：只認節點不夠——若改成「系統維護中」，會被當成 L＝∅ 而隱藏全部主檔列
    if len(empty_nodes) > 1 or (empty_nodes and text_of(empty_nodes[0]).strip() != "尚無資料"):
        raise ScrapeError(f"{category}：空狀態節點內容不是「尚無資料」（疑似維護或改版）")
    empty = bool(empty_nodes)
    rows, pager = [], None
    for tr in _grid_rows(grid):
        cls = tr.attrs.get("class", "")
        if cls in ("grvRow", "grvAlternatingRow"):
            rows.append(_parse_list_row(tr, category))
        elif cls == "grvHeader":
            continue
        elif empty and find_by_id(tr, GRID_ID + "_lbEmpty") is not None:
            continue
        else:
            parsed = _parse_pager(tr)
            if parsed is None or pager is not None:
                raise ScrapeError(f"{category}：無法辨識的列表列（疑似改版）")
            pager = parsed
    if empty and (rows or pager):
        raise ScrapeError(f"{category}：「尚無資料」與資料列同時出現")
    current, pages = pager if pager else (None, set())
    return ListPage(rows, current, pages, empty)


def check_scan(pages, category):
    """D7 完整性守門（整類）：每頁筆數、案件編號不重複、日期非遞增。"""
    last = len(pages) - 1
    for i, page in enumerate(pages):
        n = len(page.rows)
        if i < last and n != PAGE_SIZE:
            raise ScrapeError(f"{category}：第 {i + 1} 頁 {n} 筆，非末頁應為 {PAGE_SIZE} 筆")
        if i == last and not page.empty and not 1 <= n <= PAGE_SIZE:
            raise ScrapeError(f"{category}：末頁 {n} 筆，超出 1～{PAGE_SIZE}")
    rows = [r for p in pages for r in p.rows]
    cases = [r.case_no for r in rows]
    if len(cases) != len(set(cases)):
        raise ScrapeError(f"{category}：案件編號重複（疑似翻頁位移或重複頁）")
    dates = [r.date for r in rows]
    if any(a < b for a, b in zip(dates, dates[1:])):
        raise ScrapeError(f"{category}：日期非新→舊排序")
    return rows


# ----------------------------------------------------------------------
# 詳情頁
# ----------------------------------------------------------------------
def _span(root, suffix):
    node = find_by_id(root, "ContentPlaceHolder1_" + suffix)
    return text_of(node).strip() if node is not None else None


def parse_detail(text):
    """詳情頁 → dict；歷次表依頁面順序。欄位缺漏以 None 表示，由 validate_detail 判定。"""
    root = parse_html(text)
    history = []
    i = 0
    while True:
        content = find_by_id(root, f"ContentPlaceHolder1_grvPublishList_lblPublishContent_{i}")
        if content is None:
            break
        history.append({
            "reason": _span(root, f"grvPublishList_lblPublishShortageCause_{i}"),
            "text": text_of(content, br=BR_MARK),
            "date": _span(root, f"grvPublishList_lblPublishUpdateTime_{i}"),
        })
        i += 1
    return {
        "case_no": _span(root, "lblSystemNo"),
        "name_zh": _span(root, "lblProductNameC"),
        "name_en": _span(root, "lblProductNameE"),
        "license": _span(root, "lblLicense"),
        "history": history,
    }


_BR_AFTER_NEWLINE = re.compile("\n[ \t]*" + re.escape(BR_MARK))


def display_text(raw):
    """評估結果說明 → 顯示用文字：`<br>` 轉換行、統一 CRLF（與 opendata 一致），只去整段頭尾空白。

    dsms 現行寫法是「原始換行＋`<br/>`」，兩者合計只算一個換行；只有 `<br>` 沒有原始換行時
    也要換行（R5：原本忽略 `<br>`，替代藥清單會黏在一起）。
    """
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _BR_AFTER_NEWLINE.sub("\n", text).replace(BR_MARK, "\n")
    return text.strip().replace("\n", "\r\n")


def latest_history(detail, row, category, today):
    """歷次表最新一列（D7(d)、§6.2）；日期須等於列表日期，同日多列須內容相同。"""
    history = detail["history"]
    if not history:
        raise ScrapeError(f"{category} {row.case_no}：詳情頁沒有歷次表")
    for h in history:
        check_date(h["date"], today, f"{category} {row.case_no} 歷次表")
    newest = max(h["date"] for h in history)
    if newest != row.date:
        raise ScrapeError(f"{category} {row.case_no}：詳情最新日期 {newest} ≠ 列表日期 {row.date}"
                          "（列表抓完後網站已更新？）")
    same_day = [h for h in history if h["date"] == newest]
    # R5：規格要求「內容完全相同」；用 norm 比較會把換行不同的兩版當成相同
    if len({display_text(h["text"]) for h in same_day}) != 1:
        raise ScrapeError(f"{category} {row.case_no}：同日期有多列且內容不同，無法判定有效版本")
    text = display_text(same_day[0]["text"])
    if not text:
        raise ScrapeError(f"{category} {row.case_no}：評估結果說明為空")
    return text


def validate_detail(detail, row, category, today):
    """詳情頁 → 與 opendata 同構的 record（§6.2）；違反契約即 raise ScrapeError。

    許可證字號為空 → 回傳 None（排除，不比對）。實測這類是證照逾期的核醫套組，
    opendata 從不收錄空證號的品項；納入會讓差異永遠無法歸零（使用者決策 A，
    2026-10-26）。排除的筆數由呼叫端寫入輸出，不會靜默消失。
    """
    if detail["case_no"] != row.case_no:
        raise ScrapeError(f"{category}：詳情案件 {detail['case_no']!r} ≠ 列表 {row.case_no!r}")
    if not detail["name_zh"] or norm(detail["name_zh"]) != norm(row.name_zh):
        raise ScrapeError(f"{category} {row.case_no}：詳情品名與列表不符")
    license_no = (detail["license"] or "").strip()
    if not license_no and detail["license"] is not None:
        return None
    if not LICENSE_PATTERN.match(license_no):
        raise ScrapeError(f"{category} {row.case_no}：許可證字號無效（{license_no!r}）")
    check_date(row.date, today, f"{category} {row.case_no} 列表")
    name_en = (detail["name_en"] or "").strip()
    return {
        "編號": f"dsms-{row.case_no}",
        "公告更新時間": row.date,
        "中文品名": detail["name_zh"].strip() + (f"\n{name_en}" if name_en else ""),
        "許可證字號": license_no,
        "供應狀態": latest_history(detail, row, category, today),
        "_來源": "dsms",
        "_案件編號": row.case_no,
    }


# ----------------------------------------------------------------------
# 網路：每個請求前固定間隔；跳轉到非預期頁一律視為失敗
# ----------------------------------------------------------------------
class DsmsClient:
    def __init__(self, session=None, interval=REQUEST_INTERVAL, sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "Mozilla/5.0 (TFDA-drug-shortage-dashboard)")
        self.interval = interval
        self.sleep = sleep

    @staticmethod
    def list_url(category):
        return f"{BASE_URL}?s={CATEGORIES[category]['s']}"

    def _request(self, method, url, expect_path, category, **kwargs):
        self.sleep(self.interval)
        try:
            r = getattr(self.session, method)(url, timeout=REQUEST_TIMEOUT, **kwargs)
            text = r.content.decode("utf-8")
        except (requests.RequestException, UnicodeDecodeError) as exc:
            raise ScrapeError(f"{category}：請求失敗（{exc}）") from exc
        # R7：只接受 200（raise_for_status 會放過 206 等其他 2xx）
        if r.status_code != 200:
            raise ScrapeError(f"{category}：HTTP {r.status_code}")
        final = urlparse(r.url)
        s_values = parse_qs(final.query).get("s", [])
        if (final.scheme != "https" or final.hostname != DSMS_HOST
                or final.path.lower() != expect_path
                or s_values != [str(CATEGORIES[category]["s"])]):
            raise ScrapeError(f"{category}：跳轉到非預期頁 {final.scheme}://{final.hostname}{final.path}?{final.query}")
        return text

    def get_list(self, category):
        return self._request("get", self.list_url(category), "/druglist.aspx", category)

    def postback(self, category, hidden, target, argument):
        data = dict(hidden, __EVENTTARGET=target, __EVENTARGUMENT=argument)
        return self._request("post", self.list_url(category), "/druglist.aspx", category, data=data)

    def open_detail(self, category, hidden, target):
        data = dict(hidden, __EVENTTARGET=target, __EVENTARGUMENT="")
        return self._request("post", self.list_url(category), "/druginfo.aspx", category, data=data)


def scan_category(client, category):
    """翻到末頁，回傳 [(ListPage, hidden_fields)]；D7(a)(b)(c) 任一不成立 raise。"""
    text = client.get_list(category)
    pages, expected = [], 1
    while True:
        page = parse_list_page(text, category)
        if page.current is None and expected > 1:
            raise ScrapeError(f"{category}：第 {expected} 頁沒有分頁列（疑似提早截斷）")
        if page.current is not None and page.current != expected:
            raise ScrapeError(f"{category}：頁碼標記 {page.current} ≠ 預期 {expected}")
        hidden = parse_hidden_fields(text)
        pages.append((page, hidden))
        if not page.has_next:
            break
        if expected >= MAX_PAGES:
            raise ScrapeError(f"{category}：第 {MAX_PAGES} 頁仍有下一頁，超過翻頁上限")
        expected += 1
        text = client.postback(category, hidden, GRID_TARGET, f"Page${expected}")
    if not pages[0][0].rows and not pages[0][0].empty:
        raise ScrapeError(f"{category}：列表沒有資料列也沒有「尚無資料」標記")
    check_scan([p for p, _ in pages], category)
    return pages


def observe(client):
    """一輪掃描（s3→s4→s2）：{category: pages 或 ScrapeError}。"""
    result = {}
    for category in SCAN_ORDER:
        try:
            result[category] = scan_category(client, category)
        except ScrapeError as exc:
            result[category] = exc
    return result


def _signature(pages):
    return [r.signature() for page, _ in pages for r in page.rows]


def observe_twice(client, attempts=MAX_ATTEMPTS):
    """D8：兩輪掃描逐列相同才採信；不同則整次重試，仍不同 → 三類 error。

    回傳 {category: pages 或 ScrapeError}，只來自最後一次（一致的）觀測。
    """
    for attempt in range(1, attempts + 1):
        first, second = observe(client), observe(client)
        consistent = True
        for category in SCAN_ORDER:
            a, b = first[category], second[category]
            if isinstance(a, ScrapeError) or isinstance(b, ScrapeError):
                continue  # 該類本身已失敗，由下方逐類處理
            if _signature(a) != _signature(b):
                consistent = False
        if consistent:
            return {c: (first[c] if isinstance(first[c], ScrapeError) else second[c])
                    for c in SCAN_ORDER}
        print(f"⚠️ 第 {attempt} 次觀測：兩輪掃描結果不一致（掃描中網站有變動？）")
    err = ScrapeError("兩輪掃描結果不一致（重試後仍是），無法確認快照完整")
    return {c: err for c in SCAN_ORDER}


# ----------------------------------------------------------------------
# 差異計算（D5／D6）
# ----------------------------------------------------------------------
def main_name_key(row, category):
    """主檔 `中文品名`（「中文\\n英文」）→ 品名鍵；結構不支援 → 該類 error（S8）。"""
    name = row.get("中文品名") or ""
    if name.count("\n") != 1:
        raise ScrapeError(f"{category}：主檔列「{name[:20]}」的中文品名結構不支援，無法可靠比對")
    return norm(name.split("\n")[0])


def main_unit(row, category):
    key = (main_name_key(row, category), row.get("公告更新時間") or "")
    if CATEGORIES[category]["compare_content"]:
        key += (norm(row.get("許可證字號")), norm(row.get("供應狀態")))
    return key


def record_unit(record, category):
    """補抓 record 的比較單位；s2 只用列表欄位（N9）。"""
    key = (norm(record["中文品名"].split("\n")[0]), record["公告更新時間"])
    if CATEGORIES[category]["compare_content"]:
        key += (norm(record["許可證字號"]), norm(record["供應狀態"]))
    return key


def diff_units(main_items, site_items, category):
    """多重集合差：(只在網站的 items, 只在主檔的 items)。

    同一單位在兩邊次數不同且任一邊 > 1 → 無法確認對象，raise（D7(e)）。
    """
    main_count = Counter(u for u, _ in main_items)
    site_count = Counter(u for u, _ in site_items)
    for unit in set(main_count) | set(site_count):
        co, cl = main_count[unit], site_count[unit]
        if co != cl and max(co, cl) > 1:
            raise ScrapeError(f"{category}：同一比較單位在主檔 {co} 筆、網站 {cl} 筆，無法確認對象")
    added = [item for u, item in site_items if site_count[u] > main_count[u]]
    removed = [item for u, item in main_items if main_count[u] > site_count[u]]
    return added, removed


def supersede_entry(row, category):
    fingerprint = norm(row.get("供應狀態")) if CATEGORIES[category]["compare_content"] else None
    return {
        "品名鍵": main_name_key(row, category),
        "公告更新時間": row.get("公告更新時間"),
        "許可證字號": row.get("許可證字號"),
        "指紋": fingerprint,
    }


def check_cap(supersedes, main_rows, category):
    """D9 熔斷：supersedes > max(3, floor(2% × |O|)) → error；不自動放寬。"""
    cap = max(CAP_MIN, int(CAP_RATIO * len(main_rows)))
    if len(supersedes) > cap:
        raise ScrapeError(f"{category}：supersedes {len(supersedes)} 筆超過熔斷上限 {cap}"
                          "（改版或大量修訂？確認後人工調整 CAP_*）")


def process_category(client, category, pages, main, today):
    """單類：取詳情 → 差異 → 熔斷。回傳成功結果 dict；失敗 raise ScrapeError。"""
    main_rows = main["datasets"][CATEGORIES[category]["dataset"]]
    main_items = [(main_unit(r, category), r) for r in main_rows]
    located = [(row, hidden) for page, hidden in pages for row in page.rows]

    excluded = []

    def fetch(row, hidden):
        record = validate_detail(parse_detail(client.open_detail(category, hidden, row.target)),
                                 row, category, today)
        if record is None:
            excluded.append({"_案件編號": row.case_no, "公告更新時間": row.date, "中文品名": row.name_zh})
        return record

    if CATEGORIES[category]["compare_content"]:
        records = [r for r in (fetch(row, hidden) for row, hidden in located) if r is not None]
        added, removed = diff_units(main_items, [(record_unit(r, category), r) for r in records],
                                    category)
    else:
        site_items = [((norm(row.name_zh), row.date), (row, hidden)) for row, hidden in located]
        added_rows, removed = diff_units(main_items, site_items, category)
        added = [r for r in (fetch(row, hidden) for row, hidden in added_rows) if r is not None]
    supersedes = [supersede_entry(r, category) for r in removed]
    check_cap(supersedes, main_rows, category)
    return {
        "scanned": {"pages": len(pages), "rows": len(located)},
        "additions": added,
        "supersedes": supersedes,
        "excluded_no_license": excluded,
    }


# ----------------------------------------------------------------------
# 主檔、前檔、輸出
# ----------------------------------------------------------------------
def load_main(path):
    """主檔是比對基準；不存在、壞、結構不符一律 MainFileError（整批中止）。"""
    try:
        with open(path, encoding="utf-8") as f:
            main = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise MainFileError(f"無法讀取主檔 {path}：{exc}") from exc
    datasets = main.get("datasets") if isinstance(main, dict) else None
    if not isinstance(datasets, dict):
        raise MainFileError("主檔缺 datasets")
    # last_updated 是各類 base 的來源；缺漏或格式錯會產出「基準不明」的成功快照（R1）
    last_updated = main.get("last_updated")
    try:
        datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError) as exc:
        raise MainFileError(f"主檔 last_updated 無效（{last_updated!r}）") from exc
    for spec in CATEGORIES.values():
        rows = datasets.get(spec["dataset"])
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise MainFileError(f"主檔 datasets.{spec['dataset']} 結構不符")
        for r in rows:
            for field in ("公告更新時間", "中文品名", "許可證字號", "供應狀態"):
                if not isinstance(r.get(field), str):
                    raise MainFileError(f"主檔 {spec['dataset']} 有列缺 {field}")
    return main


def _is_iso(value):
    try:
        datetime.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_main_timestamp(value):
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return True
    except (TypeError, ValueError):
        return False


def _addition_problems(r, category):
    """已存檔的 addition 是否符合 §6.2（與 validate_detail 的產出同一契約）。"""
    if not isinstance(r, dict):
        return ["addition 不是物件"]
    case = r.get("_案件編號")
    checks = [
        (isinstance(case, str) and CASE_PATTERN.match(case), "案件編號無效"),
        (r.get("編號") == f"dsms-{case}", "編號與案件編號不對應"),
        (parse_date(r.get("公告更新時間")) is not None, "日期無效"),
        (isinstance(r.get("中文品名"), str) and r["中文品名"].strip(), "中文品名為空"),
        (isinstance(r.get("許可證字號"), str) and LICENSE_PATTERN.match(r["許可證字號"]), "證號無效"),
        (isinstance(r.get("供應狀態"), str) and r["供應狀態"].strip(), "供應狀態為空"),
        (r.get("_來源") == "dsms", "來源不是 dsms"),
    ]
    return [f"{category} addition {case!r}：{msg}" for ok, msg in checks if not ok]


def _supersede_problems(e, category):
    if not isinstance(e, dict):
        return [f"{category} supersede 不是物件"]
    fingerprint_ok = (isinstance(e.get("指紋"), str) if CATEGORIES[category]["compare_content"]
                      else e.get("指紋") is None)
    checks = [
        (isinstance(e.get("品名鍵"), str) and e["品名鍵"], "品名鍵為空"),
        (parse_date(e.get("公告更新時間")) is not None, "日期無效"),
        (isinstance(e.get("許可證字號"), str) and e["許可證字號"].strip(), "證號為空"),
        (fingerprint_ok, "指紋型別與類別不符"),
    ]
    return [f"{category} supersede：{msg}" for ok, msg in checks if not ok]


def category_problems(cat, category):
    """單類輸出契約（§6.1）；回傳問題清單，空清單代表合法。"""
    if not isinstance(cat, dict):
        return [f"{category}：不是物件"]
    problems = []
    if cat.get("dataset") != CATEGORIES[category]["dataset"]:
        problems.append(f"{category}：dataset 不符")
    state = cat.get("state")
    if state not in ("ok", "error") or (state == "ok") != (cat.get("error") is None):
        problems.append(f"{category}：state／error 不一致")
    lists = [cat.get(k) for k in ("additions", "supersedes", "excluded_no_license")]
    if not all(isinstance(x, list) for x in lists):
        return problems + [f"{category}：additions／supersedes／excluded_no_license 不是陣列"]
    if cat.get("last_success_at") is None:
        if state == "ok" or cat.get("base") is not None or lists[0] or lists[1]:
            problems.append(f"{category}：沒有成功紀錄卻帶有結果或基準")
        return problems
    base = cat.get("base")
    if not (_is_iso(cat["last_success_at"]) and isinstance(cat.get("success_run_id"), str)
            and isinstance(base, dict) and _is_main_timestamp(base.get("last_updated"))):
        problems.append(f"{category}：成功紀錄的時間、run_id 或基準無效")
    for r in lists[0]:
        problems += _addition_problems(r, category)
    for e in lists[1]:
        problems += _supersede_problems(e, category)
    return problems


def output_problems(payload):
    """整份補抓檔的契約；讀前檔與寫檔前都用這一套（R3）。"""
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return ["schema 不符"]
    if not isinstance(payload.get("run_id"), str) or not isinstance(payload.get("generated_at"), str):
        return ["缺 run_id 或 generated_at"]
    categories = payload.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(SCAN_ORDER):
        return ["categories 不是 s2／s3／s4"]
    return [p for c in SCAN_ORDER for p in category_problems(categories[c], c)]


def load_previous(path):
    """前檔：不存在、無法解析、或任何一處違反輸出契約 → None（視同首次，不沿用任何舊結果）。

    整份丟棄而非逐類挑選：損壞代表產出端或檔案本身出了問題，部分沿用無法保證正確（§6.3）。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ 前檔 {path} 無法讀取，視同首次執行：{exc}")
        return None
    problems = output_problems(previous)
    if problems:
        print(f"⚠️ 前檔 {path} 違反輸出契約，視同首次執行：{problems[:3]}")
        return None
    return previous


def carried_over(previous, category):
    """失敗類別沿用前檔該類的上次成功結果；沒有可用結果 → 空結果（D4）。"""
    cat = (previous or {}).get("categories", {}).get(category)
    if cat and cat.get("last_success_at") is not None:
        carried = {k: cat.get(k) for k in
                   ("last_success_at", "success_run_id", "base", "scanned", "additions", "supersedes")}
        carried["excluded_no_license"] = cat.get("excluded_no_license") or []
        return carried
    return {"last_success_at": None, "success_run_id": None, "base": None,
            "scanned": None, "additions": [], "supersedes": [], "excluded_no_license": []}


def build_output(outcomes, previous, main, now, run_id):
    base = {"last_updated": main.get("last_updated"),
            "upstream_max_date": main.get("upstream_max_date")}
    categories = {}
    for category in SCAN_ORDER:
        outcome = outcomes[category]
        entry = {"dataset": CATEGORIES[category]["dataset"]}
        if isinstance(outcome, ScrapeError):
            entry.update(state="error", error=str(outcome), **carried_over(previous, category))
        else:
            entry.update(state="ok", error=None, last_success_at=now.isoformat(timespec="seconds"),
                         success_run_id=run_id, base=base, **outcome)
        categories[category] = entry
    return {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"),
            "run_id": run_id, "categories": categories}


def write_atomic(path, payload):
    """先寫暫存檔再 os.replace 原子替換；失敗時清除暫存並保留原檔。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)  # 同目錄內 rename → 原子操作
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def run(main_path=MAIN_PATH, output_path=OUTPUT_PATH, client=None, now=None):
    """補抓主流程；回傳 exit 碼（0／2），主檔不可用時 raise MainFileError。"""
    now = now or datetime.now(TAIPEI_TZ)
    run_id = f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"
    main = load_main(main_path)
    previous = load_previous(output_path)
    client = client or DsmsClient()

    observed = observe_twice(client)
    outcomes = {}
    for category in SCAN_ORDER:
        pages = observed[category]
        if isinstance(pages, ScrapeError):
            outcomes[category] = pages
            continue
        try:
            outcomes[category] = process_category(client, category, pages, main, now.date())
        except ScrapeError as exc:
            outcomes[category] = exc

    payload = build_output(outcomes, previous, main, now, run_id)
    problems = output_problems(payload)
    if problems:
        # 產出端 bug：寧可不寫檔（前端會因過期亮紅），也不發布違反契約的檔案
        raise RuntimeError(f"輸出違反契約，未寫檔：{problems[:5]}")
    write_atomic(output_path, payload)
    for category in SCAN_ORDER:
        c = payload["categories"][category]
        if c["state"] == "ok":
            print(f"✅ {category}：additions {len(c['additions'])}、supersedes {len(c['supersedes'])}"
                  f"（{c['scanned']['pages']} 頁 {c['scanned']['rows']} 筆；"
                  f"空證號排除 {len(c['excluded_no_license'])} 筆）")
        else:
            print(f"❌ {category}：{c['error']}（沿用上次成功結果：{c['last_success_at']}）")
    return 0 if all(c["state"] == "ok" for c in payload["categories"].values()) else 2


def main():
    print(f"🚀 dsms 補抓開始（{datetime.now(TAIPEI_TZ).isoformat(timespec='seconds')}）")
    try:
        code = run()
    except MainFileError as exc:
        print(f"❌ 主檔不可用，未寫檔：{exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
