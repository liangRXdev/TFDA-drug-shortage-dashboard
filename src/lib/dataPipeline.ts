// ----------------------------------------------------------------------
// 資料管線純函式（自 App.tsx 抽出，行為保持一致以利單元測試）
//
// 這個模組刻意「零 React、零 Vite 相依」，所有函式皆為 pure function，
// 可在 node 環境直接 import 測試。抽出動作為 behavior-preserving refactor：
// 邏輯與 App.tsx 原始實作逐行對應，未修正任何已知缺陷。
// 已知缺陷以 TODO 標註並指向 .ai-review/verdict.md 之 finding 編號。
// ----------------------------------------------------------------------

export type Theme = 'red' | 'amber' | 'emerald';

export interface DrugRecord {
  編號: string;
  中文品名: string;
  許可證字號: string;
  供應狀態: string;
  公告更新時間: string;
  _theme?: Theme;
  _days?: number;
  _altText?: string | null;
}

export interface SupplyData {
  last_updated: string;
  datasets: { [key: string]: DrugRecord[] };
}

export type SortMode = 'newest' | 'longest' | 'name';

// ----------------------------------------------------------------------
// 嚴格日期解析（西元 YYYY/MM/DD，日可省略預設為 1 號）
//
// 修正 CR-04：不再依賴實作相依的 new Date("YYYY/MM/DD")。以 regex 解析後
// 驗證月/日範圍且無 rollover（如 2/30），無效日期回傳 null，避免 NaN 污染
// resolvedDates 與排序比較。供應狀態內文的民國日期不在此處理。
// ----------------------------------------------------------------------
export function parseTfdaDate(dateStr: string): number | null {
  if (!dateStr) return null;
  const m = dateStr.trim().match(/^(\d{4})\/(\d{1,2})(?:\/(\d{1,2}))?$/);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = m[3] === undefined ? 1 : Number(m[3]);
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return null;
  return d.getTime();
}

// ----------------------------------------------------------------------
// 公告距今天數
//
// CR-03 已修正：此值為「距公告更新日」的天數，並非缺藥起始日。
// UI 已改標「公告距今 N 天」（App.tsx DrugCard），不再誤稱「缺藥 N 天」。
// ----------------------------------------------------------------------
export const getDaysDiff = (dateStr: string): number => {
  const t = parseTfdaDate(dateStr);
  if (t === null) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / (1000 * 60 * 60 * 24)));
};

// ----------------------------------------------------------------------
// 資料時效（CR-06）
//
// last_updated 由 ETL 產出，格式為 "YYYY-MM-DD HH:MM:SS"（亦容忍 ISO 的 T 分隔）。
// 用嚴格 regex 解析，避免 new Date("YYYY-MM-DD HH:MM:SS") 在 Safari 等實作回 NaN。
// 每週更新一次，逾 STALE_THRESHOLD_DAYS 即視為超過預定更新週期，前端須醒目提示。
// ----------------------------------------------------------------------
export const STALE_THRESHOLD_DAYS = 10;

export function parseLastUpdated(s: string): number | null {
  if (!s) return null;
  const m = s.trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const dt = new Date(year, month - 1, day, Number(m[4]), Number(m[5]), Number(m[6] ?? '0'));
  if (dt.getFullYear() !== year || dt.getMonth() !== month - 1 || dt.getDate() !== day) return null;
  return dt.getTime();
}

export function getDataAgeDays(lastUpdated: string, now: number = Date.now()): number | null {
  const t = parseLastUpdated(lastUpdated);
  if (t === null) return null;
  return Math.max(0, Math.floor((now - t) / (1000 * 60 * 60 * 24)));
}

export function isDataStale(lastUpdated: string, now: number = Date.now()): boolean {
  const age = getDataAgeDays(lastUpdated, now);
  return age !== null && age > STALE_THRESHOLD_DAYS;
}

// ----------------------------------------------------------------------
// 替代藥萃取
//
// TODO(CR-07): 寬鬆匹配為刻意的高召回取捨，但目前會把非藥名片段
//   （如「與缺藥品項成分不盡相似」「(詳述如下)」「的病人」「圖卡 URL」）
//   當成替代藥名顯示。應加 confidence/provenance，而非收緊 regex。此處保留原行為。
// ----------------------------------------------------------------------
export const extractAlternative = (text: string): string | null => {
  if (!text) return null;
  const match = text.match(/(?:建議替代|替代藥品|替代品項|改用|可由)[：:\s]*([^。，\n;；之]+)/);
  return match ? match[1].trim() : null;
};

// ----------------------------------------------------------------------
// 預計恢復時間萃取
//
// 修正 CR-12：JSON.parse 後換行為真實 \r\n 控制字元，先正規化為 \n，
// 並在字元類排除 \n，避免擷取跨越段落抓入下一段內容。
// ----------------------------------------------------------------------
export const extractRecoveryTime = (text: string): string | null => {
  if (!text) return null;
  const normalized = text.replace(/\r\n/g, '\n');
  const match = normalized.match(/(無法預計[^。，,\n]*|預計[^。，\n]*(恢復|供應)[^。，\n]*)/);
  return match ? match[0] : null;
};

// ----------------------------------------------------------------------
// 依年月分組
// ----------------------------------------------------------------------
export interface MonthGroupEntry {
  month: string;
  items: DrugRecord[];
}
export interface YearGroupEntry {
  year: string;
  months: MonthGroupEntry[];
}

export function groupByYearMonth(list: DrugRecord[]): YearGroupEntry[] {
  const map: Record<string, Record<string, DrugRecord[]>> = {};
  list.forEach(item => {
    const parts = (item.公告更新時間 || '').split('/');
    const year = parts[0] || '未知';
    const month = parts[1]?.padStart(2, '0') || '00';
    if (!map[year]) map[year] = {};
    if (!map[year][month]) map[year][month] = [];
    map[year][month].push(item);
  });
  return Object.entries(map)
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([year, months]) => ({
      year,
      months: Object.entries(months)
        .sort(([a], [b]) => b.localeCompare(a))
        .map(([month, items]) => ({ month, items }))
    }));
}

// ----------------------------------------------------------------------
// 資料清洗 + 殭屍品項清除 + meta 掛載
//
// 修正 CR-04：日期比較改用嚴格 parseTfdaDate()，無效日期跳過而非寫入 NaN，
//   避免殭屍品項因 NaN 比較永遠無法被清除。
// TODO(CR-08): 未對完全重複列去重（同資料集＋證號＋日期＋狀態）。此處保留原行為。
// ----------------------------------------------------------------------
export interface CleanedData {
  all: DrugRecord[];
  availableYears: string[];
  noAlt: number;
  withAlt: number;
  resolved: number;
}

export function cleanSupplyData(data: SupplyData | null): CleanedData {
  if (!data) return { all: [], availableYears: [], noAlt: 0, withAlt: 0, resolved: 0 };

  const raw106 = (data.datasets['54506_resolved'] || []).map(i => ({ ...i, _theme: 'emerald' as Theme }));
  const raw104 = (data.datasets['54504_with_alternative'] || []).map(i => ({ ...i, _theme: 'amber' as Theme }));
  const raw105 = (data.datasets['54505_no_alternative'] || []).map(i => ({ ...i, _theme: 'red' as Theme }));

  const resolvedDates = new Map<string, number>();
  raw106.forEach(i => {
    const license = (i.許可證字號 || '').trim();
    if (!license) return;
    const dTime = parseTfdaDate(i.公告更新時間);
    if (dTime === null) return; // 無效日期跳過，避免 NaN 污染
    const existing = resolvedDates.get(license);
    if (existing === undefined || dTime > existing) {
      resolvedDates.set(license, dTime);
    }
  });

  const isResolvedZombie = (i: DrugRecord): boolean => {
    const license = (i.許可證字號 || '').trim();
    if (!license) return false;
    const resTime = resolvedDates.get(license);
    const myTime = parseTfdaDate(i.公告更新時間);
    return resTime !== undefined && myTime !== null && resTime >= myTime;
  };

  const clean104 = raw104.filter(i => !isResolvedZombie(i));
  const clean105 = raw105.filter(i => !isResolvedZombie(i));

  // 修正 CR-08：移除完全重複列（同資料集＋證號＋公告日期＋供應狀態）。
  // 僅去除「完全相同的事件」，不依證號合併不同 episode，以保留事件歷史。
  const seen = new Set<string>();
  const all = [...clean105, ...clean104, ...raw106]
    .filter(i => (i.中文品名 || '').trim() || (i.許可證字號 || '').trim())
    .filter(i => {
      const key = `${i._theme}|${(i.許可證字號 || '').trim()}|${i.公告更新時間 || ''}|${i.供應狀態 || ''}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map(item => ({
      ...item,
      _days: getDaysDiff(item.公告更新時間),
      _altText: extractAlternative(item.供應狀態)
    }));

  const availableYears = Array.from(new Set(all.map(i => (i.公告更新時間 || '').split('/')[0]))).filter(Boolean).sort().reverse();

  return {
    all,
    availableYears,
    noAlt: all.filter(i => i._theme === 'red').length,
    withAlt: all.filter(i => i._theme === 'amber').length,
    resolved: all.filter(i => i._theme === 'emerald').length,
  };
}

// ----------------------------------------------------------------------
// 複合統計
//
// TODO(CR-13): uniqueDrugCount 依證號/品名去重，但圖表與「件數」按 row 累加；
//   重複列與同證號多 episode 會使數字不一致。此處保留原行為。
// ----------------------------------------------------------------------
export interface ChartDatum {
  name: string;
  '無替代(紅)': number;
  '有替代(黃)': number;
  '已解除(綠)': number;
}
export interface CompositeStats {
  uniqueDrugCount: number;
  monthlyChart: ChartDatum[];
  yearlyChart: ChartDatum[];
}

interface ChartBucket {
  label: string;
  red: number;
  amber: number;
  emerald: number;
}

export function computeCompositeStats(allData: DrugRecord[]): CompositeStats {
  if (!allData.length) return { uniqueDrugCount: 0, monthlyChart: [], yearlyChart: [] };

  // 修正：若無字號，改用品名作為唯一值辨識，避免空字號藥品互相覆蓋
  const uniqueDrugs = new Set(allData.map(item => (item.許可證字號 || item.中文品名 || '未知').trim()));

  const monthlyMap: Record<string, ChartBucket> = {};
  const yearlyMap: Record<string, ChartBucket> = {};

  allData.forEach(item => {
    const parts = (item.公告更新時間 || '').split('/');
    if (parts.length >= 2) {
      const year = parts[0];
      const month = `${parts[0]}-${parts[1].padStart(2, '0')}`;
      const theme = item._theme;

      if (!monthlyMap[month]) monthlyMap[month] = { label: month, red: 0, amber: 0, emerald: 0 };
      if (theme === 'red') monthlyMap[month].red++;
      else if (theme === 'amber') monthlyMap[month].amber++;
      else if (theme === 'emerald') monthlyMap[month].emerald++;

      if (!yearlyMap[year]) yearlyMap[year] = { label: `${year}年`, red: 0, amber: 0, emerald: 0 };
      if (theme === 'red') yearlyMap[year].red++;
      else if (theme === 'amber') yearlyMap[year].amber++;
      else if (theme === 'emerald') yearlyMap[year].emerald++;
    }
  });

  const format = (map: Record<string, ChartBucket>): ChartDatum[] =>
    Object.values(map).sort((a, b) => a.label.localeCompare(b.label)).map(d => ({
      name: d.label, '無替代(紅)': d.red, '有替代(黃)': d.amber, '已解除(綠)': d.emerald
    }));

  return { uniqueDrugCount: uniqueDrugs.size, monthlyChart: format(monthlyMap), yearlyChart: format(yearlyMap) };
}

// ----------------------------------------------------------------------
// 排序
// ----------------------------------------------------------------------
export function sortRecords(list: DrugRecord[], sortMode: SortMode): DrugRecord[] {
  const all = [...list];
  all.sort((a, b) => {
    if (sortMode === 'newest') return (parseTfdaDate(b.公告更新時間) ?? 0) - (parseTfdaDate(a.公告更新時間) ?? 0);
    if (sortMode === 'longest') return (b._days || 0) - (a._days || 0);
    if (sortMode === 'name') return (a.中文品名 || '').localeCompare(b.中文品名 || '');
    return 0;
  });
  return all;
}

// ----------------------------------------------------------------------
// 篩選
// ----------------------------------------------------------------------
export interface FilterOptions {
  debouncedSearch: string;
  filterStatus: string;
  filterYear: string;
  filterMonth: string;
}

export function filterRecords(list: DrugRecord[], opts: FilterOptions): DrugRecord[] {
  const { debouncedSearch, filterStatus, filterYear, filterMonth } = opts;
  return list.filter(i => {
    const parts = (i.公告更新時間 || '').split('/');
    const matchSearch = (i.中文品名 || '').toLowerCase().includes(debouncedSearch.toLowerCase()) || (i.許可證字號 || '').includes(debouncedSearch);
    const matchStatus = filterStatus === 'all' ? true : i._theme === filterStatus;
    const matchYear = filterYear === 'all' ? true : parts[0] === filterYear;
    const matchMonth = filterMonth === 'all' ? true : parts[1]?.padStart(2, '0') === filterMonth;
    return matchSearch && matchStatus && matchYear && matchMonth;
  });
}

// ----------------------------------------------------------------------
// 清單可見資料選取（CR-09）
//
// 修正 CR-09：明確定義「顯示最新十筆」語意 = 依公告日期最新的 10 筆，
// 不受 sortMode 影響、且刻意忽略 search/status/year/month（呼叫端須停用該些控制項）。
// 一般模式則先排序再套用篩選。
// ----------------------------------------------------------------------
export interface VisibleOptions extends FilterOptions {
  showLatestTen: boolean;
  sortMode: SortMode;
}

export function selectVisibleRecords(list: DrugRecord[], opts: VisibleOptions): DrugRecord[] {
  if (opts.showLatestTen) {
    return sortRecords(list, 'newest').slice(0, 10);
  }
  return filterRecords(sortRecords(list, opts.sortMode), opts);
}

// ----------------------------------------------------------------------
// 替代藥信心分級（CR-07）
//
// 不收緊擷取 regex（維持高召回），改在顯示層加 provenance：
// - high：像藥名（含許可證號、Latin 藥名、或 ◎ 清單標記）→ 可顯示為替代品候選
// - low：URL、明顯泛稱/非藥名片段、過短 → 不當成藥名，僅提示「請展開查看」
// ----------------------------------------------------------------------
export type AltConfidence = 'high' | 'low';

const ALT_LOW_MARKERS = /(詳述如下|不盡相似|請洽|評估|病人|如下|其他合適|請參|依臨床)/;

export function alternativeConfidence(altText: string | null | undefined): AltConfidence | null {
  if (!altText) return null;
  const t = altText.trim();
  if (!t) return null;
  if (/https?:\/\//.test(t)) return 'low';
  if (ALT_LOW_MARKERS.test(t)) return 'low';
  if (t.length < 3) return 'low';
  if (/字第\s*\d+\s*號/.test(t) || /[A-Za-z]{3,}/.test(t) || t.includes('◎')) return 'high';
  return 'low';
}

// ----------------------------------------------------------------------
// 執行期資料結構守衛（CR-10）
//
// 前端 fetch 之第二道防線：確認 last_updated 為字串、datasets 為物件，
// 且出現的資料集值皆為陣列。與 ETL fail-closed 互補，非取代。
// ----------------------------------------------------------------------
export function isSupplyData(x: unknown): x is SupplyData {
  if (!x || typeof x !== 'object') return false;
  const o = x as Record<string, unknown>;
  if (typeof o.last_updated !== 'string') return false;
  if (!o.datasets || typeof o.datasets !== 'object') return false;
  for (const v of Object.values(o.datasets as Record<string, unknown>)) {
    if (!Array.isArray(v)) return false;
  }
  return true;
}
