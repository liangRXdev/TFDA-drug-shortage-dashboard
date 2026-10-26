// ----------------------------------------------------------------------
// dsms 公告頁補抓（增量 S，規格 .ai-review/plan-supplement.md r4）
//
// 補抓端（scripts/supplement_scraper.py）已算好 additions／supersedes，
// 前端只做機械式套用：顯示結果 = f(原始主檔, 補抓檔)，每次都從原始主檔計算，
// 相同輸入得到相同結果（D2）。之後再交給既有 cleanSupplyData（N2，不改）。
//
// 安全條件（D10）：會讓缺藥消失的輸入——supersedes 與 s2（已恢復）additions——
// 只有在三類都來自同一次執行、都是 ok、都新鮮、主檔版本不舊於各類基準時才套用；
// 否則只套用 s3/s4 additions，並亮紅色警示。寧可新舊並列，不可藏掉缺藥。
// ----------------------------------------------------------------------
import { type DrugRecord, type SupplyData, parseLastUpdated, parseTfdaDate } from './dataPipeline';

// 比較用空白集合：明列而不用 \s，因為 Python 與 JS 的 \s 定義不同。
// 必須與 scripts/supplement_scraper.py 的 WHITESPACE 逐字相同。
// \x1c-\x1f 是 Python str.isspace() 視為空白的控制字元，刻意列入以與後端一致。
// eslint-disable-next-line no-control-regex
const WHITESPACE = /[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\u200b\ufeff]/g;

export const SUPPLEMENT_URL_PATH = 'data/supply_supplement.json';
export const SUPPLEMENT_STALE_DAYS = 3;
export const SUPPLEMENT_TIMEOUT_MS = 8000;
// 補抓檔由使用者電腦產生，瀏覽者時鐘可能略有偏差；超過此容許量的未來時間視為無效
export const CLOCK_SKEW_TOLERANCE_MS = 5 * 60 * 1000;

export type CategoryKey = 's3' | 's4' | 's2';
export const CATEGORY_ORDER: readonly CategoryKey[] = ['s3', 's4', 's2'];

export const CATEGORY_META: Record<CategoryKey, {
  dataset: string; label: string; compareContent: boolean; listUrl: string;
}> = {
  s3: { dataset: '54504_with_alternative', label: '有替代', compareContent: true,
        listUrl: 'https://dsms.fda.gov.tw/DrugList.aspx?s=3' },
  s4: { dataset: '54505_no_alternative', label: '無替代', compareContent: true,
        listUrl: 'https://dsms.fda.gov.tw/DrugList.aspx?s=4' },
  s2: { dataset: '54506_resolved', label: '已恢復', compareContent: false,
        listUrl: 'https://dsms.fda.gov.tw/DrugList.aspx?s=2' },
};

export interface SupersedeEntry {
  品名鍵: string;
  公告更新時間: string;
  許可證字號: string;
  指紋: string | null;
}

export interface SupplementCategory {
  dataset: string;
  state: 'ok' | 'error';
  error: string | null;
  last_success_at: string | null;
  success_run_id: string | null;
  base: { last_updated: string | null; upstream_max_date: string | null } | null;
  additions: DrugRecord[];
  supersedes: SupersedeEntry[];
}

export interface SupplementData {
  schema: 1;
  generated_at: string;
  run_id: string;
  categories: Record<CategoryKey, SupplementCategory>;
}

export type SupplementLoad =
  | { status: 'ok'; data: SupplementData }
  | { status: 'error'; reason: string };

export interface SupplementResult {
  /** 套用後的資料，交給 cleanSupplyData */
  data: SupplyData;
  /** 紅色警示（逐條列出，互不遮蔽） */
  warnings: string[];
  /** 琥珀資訊；沒有差異或不可信時為 null */
  info: string | null;
  /** D10 條件是否成立（成立才隱藏、才加入 s2 additions） */
  trusted: boolean;
  added: number;
  hidden: number;
}

export function normalizeKey(value: string | null | undefined): string {
  return (value ?? '').normalize('NFKC').replace(WHITESPACE, '');
}

// ----------------------------------------------------------------------
// 逐筆驗證（主檔的 isSupplyData 只驗頂層；補抓檔必須自己驗到每一筆）
// ----------------------------------------------------------------------
const isStr = (v: unknown): v is string => typeof v === 'string';

function isAddition(x: unknown): x is DrugRecord {
  if (!x || typeof x !== 'object') return false;
  const r = x as Record<string, unknown>;
  return isStr(r.編號) && isStr(r.中文品名) && r.中文品名.trim() !== ''
    && isStr(r.許可證字號) && r.許可證字號.trim() !== ''
    && isStr(r.供應狀態) && r.供應狀態.trim() !== ''
    && isStr(r.公告更新時間) && parseTfdaDate(r.公告更新時間) !== null
    && r._來源 === 'dsms' && isStr(r._案件編號);
}

function isSupersede(x: unknown): x is SupersedeEntry {
  if (!x || typeof x !== 'object') return false;
  const e = x as Record<string, unknown>;
  return isStr(e.品名鍵) && e.品名鍵 !== '' && isStr(e.公告更新時間) && isStr(e.許可證字號)
    && (e.指紋 === null || isStr(e.指紋));
}

function isCategory(x: unknown, key: CategoryKey): x is SupplementCategory {
  if (!x || typeof x !== 'object') return false;
  const c = x as Record<string, unknown>;
  if (c.dataset !== CATEGORY_META[key].dataset) return false;
  if (c.state !== 'ok' && c.state !== 'error') return false;
  if (!(c.error === null || isStr(c.error))) return false;
  if (!(c.last_success_at === null || isStr(c.last_success_at))) return false;
  if (!(c.success_run_id === null || isStr(c.success_run_id))) return false;
  // base 的欄位型別必須正確：型別錯（如數字）會讓後續 parseLastUpdated 拋例外（R1）
  if (c.base !== null) {
    if (typeof c.base !== 'object' || !c.base) return false;
    const b = c.base as Record<string, unknown>;
    if (!(b.last_updated === null || isStr(b.last_updated))) return false;
    if (!(b.upstream_max_date === null || b.upstream_max_date === undefined || isStr(b.upstream_max_date))) return false;
  }
  if (!Array.isArray(c.additions) || !c.additions.every(isAddition)) return false;
  if (!Array.isArray(c.supersedes) || !c.supersedes.every(isSupersede)) return false;
  return true;
}

export function isSupplementData(x: unknown): x is SupplementData {
  if (!x || typeof x !== 'object') return false;
  const o = x as Record<string, unknown>;
  if (o.schema !== 1 || !isStr(o.run_id) || !isStr(o.generated_at)) return false;
  const cats = o.categories as Record<string, unknown> | undefined;
  if (!cats || typeof cats !== 'object') return false;
  return CATEGORY_ORDER.every(k => isCategory(cats[k], k));
}

/** 載入補抓檔；永不 reject。逾時、非 200、JSON 壞、結構不符都回 error。 */
export async function loadSupplement(
  url: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs: number = SUPPLEMENT_TIMEOUT_MS,
): Promise<SupplementLoad> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<SupplementLoad>(resolve => {
    timer = setTimeout(() => resolve({ status: 'error', reason: `逾時 ${timeoutMs / 1000} 秒` }), timeoutMs);
  });
  const attempt = (async (): Promise<SupplementLoad> => {
    try {
      const res = await fetchImpl(url, { cache: 'no-store' });
      if (!res.ok) return { status: 'error', reason: `HTTP ${res.status}` };
      let json: unknown;
      try {
        json = await res.json();
      } catch {
        return { status: 'error', reason: '回應不是 JSON' };
      }
      if (!isSupplementData(json)) return { status: 'error', reason: '補抓資料結構不符' };
      return { status: 'ok', data: json };
    } catch (e) {
      return { status: 'error', reason: e instanceof Error ? e.message : String(e) };
    }
  })();
  try {
    return await Promise.race([attempt, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

// ----------------------------------------------------------------------
// 新鮮度與版本檢查
// ----------------------------------------------------------------------
/** 距今天數；缺漏、無法解析、晚於現在（超過時鐘容許量）→ null（fail-closed）。 */
export function supplementAgeDays(lastSuccessAt: string | null, now: number): number | null {
  if (!lastSuccessAt) return null;
  const t = Date.parse(lastSuccessAt);
  if (Number.isNaN(t) || t - now > CLOCK_SKEW_TOLERANCE_MS) return null;
  return Math.max(0, (now - t) / 86400000);
}

/** 基準版本檢查：'unknown' = 無法確認（fail-closed，R1）；'older' = 主檔比基準舊；'ok'。 */
function baseStatus(main: SupplyData, cat: SupplementCategory): 'ok' | 'older' | 'unknown' {
  const baseTime = parseLastUpdated(cat.base?.last_updated ?? '');
  const mainTime = parseLastUpdated(main.last_updated);
  if (baseTime === null || mainTime === null) return 'unknown';
  return mainTime < baseTime ? 'older' : 'ok';
}

/** 該類是否帶有任何結果（首次就失敗的類別沒有結果、也沒有基準，已由 error 警示涵蓋）。 */
function hasResults(cat: SupplementCategory): boolean {
  return cat.state === 'ok' || cat.last_success_at !== null
    || cat.additions.length > 0 || cat.supersedes.length > 0;
}

function categoryWarnings(main: SupplyData, sup: SupplementData, key: CategoryKey, now: number): string[] {
  const cat = sup.categories[key];
  const label = CATEGORY_META[key].label;
  const out: string[] = [];
  if (cat.state === 'error') {
    const since = cat.last_success_at ? `沿用 ${cat.last_success_at.slice(0, 10)} 的結果` : '沒有可用的補抓結果';
    out.push(`「${label}」類補抓失敗（${cat.error ?? '原因不明'}），${since}。`);
  } else if (cat.success_run_id !== sup.run_id) {
    out.push(`「${label}」類補抓結果不是同一次執行產生。`);
  }
  const age = supplementAgeDays(cat.last_success_at, now);
  if (age === null) {
    if (cat.state === 'ok') out.push(`「${label}」類補抓更新時間不明。`);
  } else if (age > SUPPLEMENT_STALE_DAYS) {
    out.push(`「${label}」類補抓資料已 ${Math.floor(age)} 天未更新。`);
  }
  const base = baseStatus(main, cat);
  if (base === 'older') {
    out.push(`「${label}」類補抓資料比目前載入的主資料新（版本不一致），請重新整理頁面。`);
  } else if (base === 'unknown' && hasResults(cat)) {
    out.push(`「${label}」類補抓資料的比對基準版本不明，無法確認與主資料相容。`);
  }
  return out;
}

/**
 * 信任何時會因新鮮度到期而失效（R4）：各類 last_success_at + 門檻中最早、且晚於 now 者。
 * 頁面常駐時，App 在此時刻重算 applySupplement，讓過期警示與停止隱藏如期發生。
 */
export function trustExpiresAt(load: SupplementLoad | null, now: number): number | null {
  if (!load || load.status !== 'ok') return null;
  let earliest: number | null = null;
  for (const key of CATEGORY_ORDER) {
    const t = Date.parse(load.data.categories[key].last_success_at ?? '');
    if (Number.isNaN(t)) continue;
    const expires = t + SUPPLEMENT_STALE_DAYS * 86400000;
    if (expires > now && (earliest === null || expires < earliest)) earliest = expires;
  }
  return earliest;
}

// ----------------------------------------------------------------------
// 套用
// ----------------------------------------------------------------------
function mainNameKey(row: DrugRecord): string | null {
  const parts = (row.中文品名 ?? '').split('\n');
  return parts.length === 2 ? normalizeKey(parts[0]) : null;   // 結構不支援 → 永不匹配
}

function matchesSupersede(row: DrugRecord, e: SupersedeEntry, compareContent: boolean): boolean {
  return mainNameKey(row) === e.品名鍵
    && row.公告更新時間 === e.公告更新時間
    && normalizeKey(row.許可證字號) === normalizeKey(e.許可證字號)
    && (!compareContent || normalizeKey(row.供應狀態) === e.指紋);
}

function sameUnit(a: DrugRecord, b: DrugRecord, compareContent: boolean): boolean {
  const ka = normalizeKey((a.中文品名 ?? '').split('\n')[0]);
  const kb = normalizeKey((b.中文品名 ?? '').split('\n')[0]);
  if (ka !== kb || a.公告更新時間 !== b.公告更新時間) return false;
  if (!compareContent) return true;
  return normalizeKey(a.許可證字號) === normalizeKey(b.許可證字號)
    && normalizeKey(a.供應狀態) === normalizeKey(b.供應狀態);
}

/** 依數量移除：每筆 supersede 只移除一列（S7：多重集合語意）。 */
function removeSuperseded(rows: DrugRecord[], entries: SupersedeEntry[], compareContent: boolean) {
  const kept = [...rows];
  let hidden = 0;
  for (const e of entries) {
    const i = kept.findIndex(r => matchesSupersede(r, e, compareContent));
    if (i >= 0) { kept.splice(i, 1); hidden += 1; }
  }
  return { kept, hidden };
}

/** 依數量加入：主檔已有同單位的列時，略過對應筆數。 */
function addRecords(rows: DrugRecord[], additions: DrugRecord[], compareContent: boolean) {
  const consumed = new Set<number>();
  const out = [...rows];
  let added = 0;
  for (const a of additions) {
    const i = rows.findIndex((r, idx) => !consumed.has(idx) && sameUnit(r, a, compareContent));
    if (i >= 0) { consumed.add(i); continue; }
    out.push({ ...a });
    added += 1;
  }
  return { rows: out, added };
}

export function applySupplement(main: SupplyData, load: SupplementLoad, now: number = Date.now()): SupplementResult {
  const latest = main.upstream_max_date ?? '未知';
  if (load.status === 'error') {
    return {
      data: main, trusted: false, added: 0, hidden: 0, info: null,
      warnings: [`無法載入公告頁補抓資料（${load.reason}），看板目前可能僅涵蓋政府開放資料（最新公告 ${latest}）。`
        + '最新缺藥請至食藥署西藥供應資訊網站確認，切勿據此判定「沒有新缺藥」。'],
    };
  }
  const sup = load.data;
  const warnings = CATEGORY_ORDER.flatMap(k => categoryWarnings(main, sup, k, now));
  const trusted = warnings.length === 0;

  const datasets: Record<string, DrugRecord[]> = { ...main.datasets };
  let added = 0;
  let hidden = 0;
  for (const key of CATEGORY_ORDER) {
    const meta = CATEGORY_META[key];
    const cat = sup.categories[key];
    let rows = [...(main.datasets[meta.dataset] ?? [])];
    if (trusted) {
      const r = removeSuperseded(rows, cat.supersedes, meta.compareContent);
      rows = r.kept;
      hidden += r.hidden;
    }
    if (trusted || key !== 's2') {
      const r = addRecords(rows, cat.additions, meta.compareContent);
      rows = r.rows;
      added += r.added;
    }
    datasets[meta.dataset] = rows;
  }

  if (!trusted) {
    warnings.push('因補抓狀態不完整，看板暫不依官網隱藏或更新舊公告：同一藥品可能有新舊版本並列，供應說明請以官網為準。');
  }
  const info = trusted && (added > 0 || hidden > 0)
    ? `政府開放資料最新僅至 ${latest}；表中 ${added} 筆較新公告由食藥署西藥供應資訊網站補抓（標示「公告頁補抓」），`
      + `${hidden} 筆舊版公告已依官網隱藏。`
    : null;
  return { data: { ...main, datasets }, warnings, info, trusted, added, hidden };
}

/** 補抓列所屬類別的官網列表頁（徽章連結；N3：不連詳情頁）。 */
export function supplementListUrl(item: DrugRecord): string | null {
  if (item._來源 !== 'dsms') return null;
  const key: CategoryKey = item._theme === 'red' ? 's4' : item._theme === 'emerald' ? 's2' : 's3';
  return CATEGORY_META[key].listUrl;
}

// ----------------------------------------------------------------------
// 卡片身分（B9）：opendata 的「編號」跨更新不穩定（實測 234/235 變動），
// 改用內容身分＋同組序號，同證同日不同內容的兩列 key 也不相同。
// ----------------------------------------------------------------------
function hashText(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

export function recordKeys(items: DrugRecord[]): string[] {
  const seen = new Map<string, number>();
  return items.map(item => {
    const base = [item._theme ?? '', normalizeKey(item.許可證字號), item.公告更新時間,
      hashText(normalizeKey(item.供應狀態))].join('|');
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return `${base}|${n}`;
  });
}
