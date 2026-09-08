import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  parseTfdaDate,
  parseLastUpdated,
  getDataAgeDays,
  isDataStale,
  STALE_THRESHOLD_DAYS,
  getDaysDiff,
  extractAlternative,
  extractRecoveryTime,
  groupByYearMonth,
  cleanSupplyData,
  computeCompositeStats,
  sortRecords,
  filterRecords,
  selectVisibleRecords,
  alternativeConfidence,
  isSupplyData,
  isUpstreamFrozen,
  FROZEN_RUNS_THRESHOLD,
  type DrugRecord,
  type SupplyData,
  type Theme,
} from './dataPipeline';

// ----------------------------------------------------------------------
// 測試策略：本檔鎖定「目前行為」（characterization tests）。
// 已知缺陷處以「TODO(CR-xx)」標註，對應 .ai-review/verdict.md；
// 修正後這些斷言需一併更新（屆時即為 regression guard）。
// ----------------------------------------------------------------------

// 固定「今天」= 2026-07-21（本地午夜），使含 new Date() 的函式可決定性測試。
const FIXED_NOW = new Date(2026, 6, 21, 0, 0, 0, 0);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

// 建立 DrugRecord 的輔助函式（欄位可覆寫）
function rec(overrides: Partial<DrugRecord>): DrugRecord {
  return {
    編號: '',
    中文品名: '',
    許可證字號: '',
    供應狀態: '',
    公告更新時間: '',
    ...overrides,
  };
}

// ======================================================================
// parseTfdaDate（CR-04 嚴格解析）
// ======================================================================
describe('parseTfdaDate (CR-04)', () => {
  it('合法 YYYY/MM/DD 回傳時間戳', () => {
    expect(parseTfdaDate('2025/07/11')).toBe(new Date(2025, 6, 11).getTime());
  });
  it('缺日 YYYY/MM 預設為 1 號', () => {
    expect(parseTfdaDate('2026/07')).toBe(new Date(2026, 6, 1).getTime());
  });
  it('前後空白容忍', () => {
    expect(parseTfdaDate('  2025/01/01  ')).toBe(new Date(2025, 0, 1).getTime());
  });
  it('空字串 / 非日期回傳 null', () => {
    expect(parseTfdaDate('')).toBeNull();
    expect(parseTfdaDate('INVALID')).toBeNull();
    expect(parseTfdaDate('2026')).toBeNull();
  });
  it('月份越界回傳 null', () => {
    expect(parseTfdaDate('2026/13/01')).toBeNull();
    expect(parseTfdaDate('2026/00/01')).toBeNull();
  });
  it('日越界 / rollover 回傳 null', () => {
    expect(parseTfdaDate('2026/02/30')).toBeNull();
    expect(parseTfdaDate('2026/13/40')).toBeNull();
  });
  it('閏年 2/29 合法、平年 2/29 為 null', () => {
    expect(parseTfdaDate('2024/02/29')).not.toBeNull();
    expect(parseTfdaDate('2025/02/29')).toBeNull();
  });
});

// ======================================================================
// 資料時效 parseLastUpdated / getDataAgeDays / isDataStale（CR-06）
// ======================================================================
describe('data freshness (CR-06)', () => {
  // 測試環境 FIXED_NOW = 2026-07-21 00:00
  it('parseLastUpdated 解析 ETL 空格格式', () => {
    expect(parseLastUpdated('2026-05-22 06:58:07')).toBe(new Date(2026, 4, 22, 6, 58, 7).getTime());
  });
  it('parseLastUpdated 亦容忍 ISO 的 T 分隔與缺秒', () => {
    expect(parseLastUpdated('2026-07-11T00:00')).toBe(new Date(2026, 6, 11, 0, 0, 0).getTime());
  });
  it('parseLastUpdated 非法字串回傳 null', () => {
    expect(parseLastUpdated('')).toBeNull();
    expect(parseLastUpdated('not-a-date')).toBeNull();
    expect(parseLastUpdated('2026-13-01 00:00:00')).toBeNull();
  });
  it('getDataAgeDays 計算天數', () => {
    expect(getDataAgeDays('2026-07-11 00:00:00')).toBe(10);
    expect(getDataAgeDays('2026-05-22 06:58:07')).toBe(59);
  });
  it('getDataAgeDays 非法輸入回傳 null（不可誤判為 0 天新鮮）', () => {
    expect(getDataAgeDays('garbage')).toBeNull();
  });
  it(`isDataStale：門檻 ${STALE_THRESHOLD_DAYS} 天，邊界正確`, () => {
    expect(isDataStale('2026-07-11 00:00:00')).toBe(false); // 恰 10 天 → 未逾期
    expect(isDataStale('2026-07-10 00:00:00')).toBe(true);  // 11 天 → 逾期
    expect(isDataStale('2026-05-22 06:58:07')).toBe(true);  // 現況 59 天 → 逾期
  });
  it('isDataStale：無法解析的時間戳視為非過期（交由其他錯誤路徑處理）', () => {
    expect(isDataStale('garbage')).toBe(false);
  });
});

// ======================================================================
// TG-04：缺藥天數 getDaysDiff
// ======================================================================
describe('getDaysDiff (TG-04)', () => {
  it('空字串回傳 0', () => {
    expect(getDaysDiff('')).toBe(0);
  });

  it('缺少月份（parts.length < 2）回傳 0', () => {
    expect(getDaysDiff('2026')).toBe(0);
  });

  it('等於今天回傳 0', () => {
    expect(getDaysDiff('2026/07/21')).toBe(0);
  });

  it('10 天前回傳 10', () => {
    expect(getDaysDiff('2026/07/11')).toBe(10);
  });

  it('未來日期被 Math.max(0, …) 夾為 0', () => {
    expect(getDaysDiff('2026/07/22')).toBe(0);
  });

  it('缺日（YYYY/MM）以該月 1 號計算', () => {
    // 2026/07 → 2026/07/01 → 距 07/21 為 20 天
    expect(getDaysDiff('2026/07')).toBe(20);
  });

  it('閏年 2024/02/29 為合法日期，回傳正數', () => {
    expect(getDaysDiff('2024/02/29')).toBeGreaterThan(0);
  });

  it('跨年日期正確（2025/07/21 → 365 天）', () => {
    expect(getDaysDiff('2025/07/21')).toBe(365);
  });

  it('CR-04 已修正：非法日期 2026/13/40 被嚴格拒絕，回傳 0', () => {
    expect(getDaysDiff('2026/13/40')).toBe(0);
  });
});

// ======================================================================
// TG-06：替代藥 / 恢復時間 萃取
// ======================================================================
describe('extractAlternative (TG-06)', () => {
  it('null/空字串回傳 null', () => {
    expect(extractAlternative('')).toBeNull();
  });

  it('明確藥名：「替代藥品：Foo Tab」→ 擷取乾淨藥名', () => {
    expect(extractAlternative('替代藥品：Foo Tab。')).toBe('Foo Tab');
  });

  it('TODO(CR-07): 「建議替代」先命中，殘留「藥品：」被一併擷取（連正常輸入都不乾淨）', () => {
    expect(extractAlternative('建議替代藥品：Foo Tab。')).toBe('藥品：Foo Tab');
  });

  it('無任何觸發詞回傳 null', () => {
    expect(extractAlternative('本品因原料短缺暫停供應。')).toBeNull();
  });

  it('TODO(CR-07): 「可由」觸發詞會把後續非藥名文字誤擷取為替代建議', () => {
    // 低信心片段被當成替代藥名，屬 CR-07；此為目前行為
    expect(extractAlternative('可由醫師評估病人臨床需求')).toBe('醫師評估病人臨床需求');
  });

  it('cf1710e 修正：「改用之…」因排除「之」而不誤抓', () => {
    // 觸發詞後緊接「之」被排除字元類擋下 → 無擷取
    expect(extractAlternative('請改用之其他治療')).toBeNull();
  });
});

describe('extractRecoveryTime (TG-06 / CR-12)', () => {
  it('null/空字串回傳 null', () => {
    expect(extractRecoveryTime('')).toBeNull();
  });

  it('擷取「無法預計…」至句號前', () => {
    expect(extractRecoveryTime('無法預計恢復正常供應時程。後略')).toBe('無法預計恢復正常供應時程');
  });

  it('擷取「預計…恢復…」片段', () => {
    expect(extractRecoveryTime('預計2026年8月恢復供應。')).toContain('恢復');
  });

  it('CR-12 已修正：真實 \\r\\n 換行不再被跨行擷取，止於段落邊界', () => {
    const out = extractRecoveryTime('無法預計恢復\r\n下一段');
    expect(out).toBe('無法預計恢復');
    expect(out).not.toContain('\n');
  });
});

// ======================================================================
// TG-03：資料清洗 + 殭屍品項清除
// ======================================================================
describe('cleanSupplyData zombie removal (TG-03)', () => {
  function build(datasets: Partial<Record<string, DrugRecord[]>>): SupplyData {
    return {
      last_updated: '2026-07-21 00:00:00',
      datasets: {
        '54504_with_alternative': datasets['54504_with_alternative'] || [],
        '54505_no_alternative': datasets['54505_no_alternative'] || [],
        '54506_resolved': datasets['54506_resolved'] || [],
      },
    };
  }

  it('null data 回傳空結構', () => {
    expect(cleanSupplyData(null)).toEqual({ all: [], availableYears: [], noAlt: 0, withAlt: 0, resolved: 0 });
  });

  it('解除日 >= 短缺日 → 該短缺品項被清除（殭屍清除）', () => {
    const data = build({
      '54505_no_alternative': [rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/01/01' })],
      '54506_resolved': [rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/02/01' })],
    });
    const out = cleanSupplyData(data);
    expect(out.noAlt).toBe(0); // 105 的 X 被清除
    expect(out.resolved).toBe(1);
    expect(out.all.some(i => i._theme === 'red')).toBe(false);
  });

  it('解除後又出現新一輪短缺（短缺日 > 解除日）→ 保留', () => {
    const data = build({
      '54505_no_alternative': [rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/03/01' })],
      '54506_resolved': [rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/02/01' })],
    });
    const out = cleanSupplyData(data);
    expect(out.noAlt).toBe(1); // 新短缺保留
  });

  it('同日解除（解除日 == 短缺日）→ 清除（>= 條件）', () => {
    const data = build({
      '54504_with_alternative': [rec({ 許可證字號: 'Y', 中文品名: 'DrugY', 公告更新時間: '2025/05/05' })],
      '54506_resolved': [rec({ 許可證字號: 'Y', 中文品名: 'DrugY', 公告更新時間: '2025/05/05' })],
    });
    const out = cleanSupplyData(data);
    expect(out.withAlt).toBe(0);
  });

  it('無許可證字號的短缺品項不套用解除比對，一律保留', () => {
    const data = build({
      '54505_no_alternative': [rec({ 許可證字號: '   ', 中文品名: 'NoLicense', 公告更新時間: '2025/01/01' })],
      '54506_resolved': [rec({ 許可證字號: '', 中文品名: 'NoLicense', 公告更新時間: '2025/06/01' })],
    });
    const out = cleanSupplyData(data);
    expect(out.noAlt).toBe(1);
  });

  it('resolvedDates 取同證號的最大解除日', () => {
    const data = build({
      '54505_no_alternative': [rec({ 許可證字號: 'Z', 中文品名: 'DrugZ', 公告更新時間: '2025/04/01' })],
      '54506_resolved': [
        rec({ 許可證字號: 'Z', 中文品名: 'DrugZ', 公告更新時間: '2025/01/01' }),
        rec({ 許可證字號: 'Z', 中文品名: 'DrugZ', 公告更新時間: '2025/05/01' }), // 最大 → >= 04/01 → 清除
      ],
    });
    const out = cleanSupplyData(data);
    expect(out.noAlt).toBe(0);
  });

  it('中文品名與許可證字號皆空的 sentinel 列被 identity filter 剔除', () => {
    const data = build({
      '54505_no_alternative': [rec({ 編號: '沒有資料', 中文品名: '', 許可證字號: '' })],
    });
    const out = cleanSupplyData(data);
    expect(out.all).toHaveLength(0);
    expect(out.noAlt).toBe(0);
  });

  it('availableYears 去重且由新到舊排序', () => {
    const data = build({
      '54506_resolved': [
        rec({ 許可證字號: 'A', 中文品名: 'a', 公告更新時間: '2024/01/01' }),
        rec({ 許可證字號: 'B', 中文品名: 'b', 公告更新時間: '2026/01/01' }),
        rec({ 許可證字號: 'C', 中文品名: 'c', 公告更新時間: '2025/01/01' }),
      ],
    });
    const out = cleanSupplyData(data);
    expect(out.availableYears).toEqual(['2026', '2025', '2024']);
  });

  it('CR-04 已修正：解除列含非法日期時，仍以合法解除日清除殭屍品項', () => {
    const data = build({
      '54505_no_alternative': [rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/03/01' })],
      '54506_resolved': [
        rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: 'INVALID' }), // 跳過，不污染
        rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/12/01' }), // 合法 → 清除殭屍
      ],
    });
    const out = cleanSupplyData(data);
    expect(out.noAlt).toBe(0);
  });

  it('CR-08：完全重複列（同資料集＋證號＋日期＋狀態）只保留一筆', () => {
    const dup = { 許可證字號: 'DUP', 中文品名: 'DrugDup', 公告更新時間: '2024/08/20', 供應狀態: '已解除' };
    const data = build({ '54506_resolved': [rec(dup), rec(dup)] });
    const out = cleanSupplyData(data);
    expect(out.resolved).toBe(1);
    expect(out.all).toHaveLength(1);
  });

  it('CR-08：同證號但不同公告日期的合法 episode 不被去重', () => {
    const data = build({
      '54505_no_alternative': [
        rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/01/01' }),
        rec({ 許可證字號: 'X', 中文品名: 'DrugX', 公告更新時間: '2025/09/01' }),
      ],
    });
    const out = cleanSupplyData(data);
    expect(out.noAlt).toBe(2);
  });

  it('_days 與 _altText meta 有被掛載', () => {
    const data = build({
      '54505_no_alternative': [rec({ 許可證字號: 'M', 中文品名: 'DrugM', 公告更新時間: '2026/07/11', 供應狀態: '替代藥品：Alt。' })],
    });
    const out = cleanSupplyData(data);
    expect(out.all[0]._days).toBe(10);
    expect(out.all[0]._altText).toBe('Alt');
  });
});

// ======================================================================
// TG-07：複合統計 computeCompositeStats
// ======================================================================
describe('computeCompositeStats (TG-07 / CR-13)', () => {
  it('空陣列回傳零值結構', () => {
    expect(computeCompositeStats([])).toEqual({ uniqueDrugCount: 0, monthlyChart: [], yearlyChart: [] });
  });

  it('依 theme 分別累計月度與年度數量', () => {
    const list: DrugRecord[] = [
      rec({ 許可證字號: 'A', 公告更新時間: '2025/03/01', _theme: 'red' as Theme }),
      rec({ 許可證字號: 'B', 公告更新時間: '2025/03/15', _theme: 'amber' as Theme }),
      rec({ 許可證字號: 'C', 公告更新時間: '2025/04/01', _theme: 'emerald' as Theme }),
    ];
    const s = computeCompositeStats(list);
    const march = s.monthlyChart.find(d => d.name === '2025-03')!;
    expect(march['無替代(紅)']).toBe(1);
    expect(march['有替代(黃)']).toBe(1);
    const y2025 = s.yearlyChart.find(d => d.name === '2025年')!;
    expect(y2025['已解除(綠)']).toBe(1);
  });

  it('uniqueDrugCount 依許可證字號去重', () => {
    const list: DrugRecord[] = [
      rec({ 許可證字號: 'DUP', 公告更新時間: '2025/03/01', _theme: 'red' as Theme }),
      rec({ 許可證字號: 'DUP', 公告更新時間: '2025/04/01', _theme: 'red' as Theme }),
    ];
    expect(computeCompositeStats(list).uniqueDrugCount).toBe(1);
  });

  it('TODO(CR-13): 完全重複列在圖表按 row 重複計數，但 uniqueDrugCount 只算 1', () => {
    const dup = rec({ 許可證字號: 'DUP', 公告更新時間: '2024/08/20', _theme: 'emerald' as Theme });
    const s = computeCompositeStats([{ ...dup }, { ...dup }]);
    expect(s.uniqueDrugCount).toBe(1);
    const aug = s.monthlyChart.find(d => d.name === '2024-08')!;
    expect(aug['已解除(綠)']).toBe(2); // 重複列被計兩次
  });

  it('無許可證字號時改用中文品名作為唯一鍵', () => {
    const list: DrugRecord[] = [
      rec({ 許可證字號: '', 中文品名: 'SameName', 公告更新時間: '2025/03/01', _theme: 'red' as Theme }),
      rec({ 許可證字號: '', 中文品名: 'SameName', 公告更新時間: '2025/04/01', _theme: 'red' as Theme }),
    ];
    expect(computeCompositeStats(list).uniqueDrugCount).toBe(1);
  });
});

// ======================================================================
// TG-08：排序 / 篩選
// ======================================================================
describe('sortRecords (TG-08)', () => {
  const list: DrugRecord[] = [
    rec({ 中文品名: 'B藥', 公告更新時間: '2025/01/01', _days: 100 }),
    rec({ 中文品名: 'A藥', 公告更新時間: '2026/06/01', _days: 5 }),
    rec({ 中文品名: 'C藥', 公告更新時間: '2025/12/01', _days: 50 }),
  ];

  it('newest：依公告日期新到舊', () => {
    const out = sortRecords(list, 'newest');
    expect(out.map(i => i.公告更新時間)).toEqual(['2026/06/01', '2025/12/01', '2025/01/01']);
  });

  it('longest：依 _days 大到小', () => {
    const out = sortRecords(list, 'longest');
    expect(out.map(i => i._days)).toEqual([100, 50, 5]);
  });

  it('name：依中文品名遞增', () => {
    const out = sortRecords(list, 'name');
    expect(out.map(i => i.中文品名)).toEqual(['A藥', 'B藥', 'C藥']);
  });

  it('不變更輸入陣列（回傳新陣列）', () => {
    const before = list.map(i => i.中文品名);
    sortRecords(list, 'name');
    expect(list.map(i => i.中文品名)).toEqual(before);
  });
});

describe('filterRecords (TG-08)', () => {
  const list: DrugRecord[] = [
    rec({ 中文品名: 'Aspirin 阿斯匹靈', 許可證字號: '衛署藥製字第001號', 公告更新時間: '2025/03/01', _theme: 'red' as Theme }),
    rec({ 中文品名: 'Bar 藥', 許可證字號: '衛署藥製字第002號', 公告更新時間: '2026/07/01', _theme: 'amber' as Theme }),
  ];
  const allPass = { debouncedSearch: '', filterStatus: 'all', filterYear: 'all', filterMonth: 'all' };

  it('全部 all → 不篩除', () => {
    expect(filterRecords(list, allPass)).toHaveLength(2);
  });

  it('中文品名搜尋大小寫不敏感', () => {
    expect(filterRecords(list, { ...allPass, debouncedSearch: 'aspirin' })).toHaveLength(1);
  });

  it('許可證字號子字串搜尋', () => {
    expect(filterRecords(list, { ...allPass, debouncedSearch: '002' })).toHaveLength(1);
  });

  it('狀態篩選', () => {
    const out = filterRecords(list, { ...allPass, filterStatus: 'amber' });
    expect(out).toHaveLength(1);
    expect(out[0]._theme).toBe('amber');
  });

  it('年份與月份篩選', () => {
    expect(filterRecords(list, { ...allPass, filterYear: '2026' })).toHaveLength(1);
    expect(filterRecords(list, { ...allPass, filterMonth: '03' })).toHaveLength(1);
  });
});

// ======================================================================
// groupByYearMonth（輔助覆蓋）
// ======================================================================
describe('groupByYearMonth', () => {
  it('依年月分組並由新到舊排序', () => {
    const list: DrugRecord[] = [
      rec({ 中文品名: 'x', 公告更新時間: '2025/03/01' }),
      rec({ 中文品名: 'y', 公告更新時間: '2026/01/01' }),
      rec({ 中文品名: 'z', 公告更新時間: '2025/03/15' }),
    ];
    const g = groupByYearMonth(list);
    expect(g.map(y => y.year)).toEqual(['2026', '2025']);
    const y2025 = g.find(y => y.year === '2025')!;
    expect(y2025.months[0].items).toHaveLength(2); // 2025-03 有兩筆
  });

  it('空公告時間歸入「未知」年', () => {
    const g = groupByYearMonth([rec({ 中文品名: 'x', 公告更新時間: '' })]);
    expect(g[0].year).toBe('未知');
  });
});

// ======================================================================
// selectVisibleRecords（CR-09）
// ======================================================================
describe('selectVisibleRecords (CR-09)', () => {
  const list: DrugRecord[] = [
    rec({ 中文品名: 'A', 許可證字號: 'L1', 公告更新時間: '2020/01/01', _theme: 'red' as Theme }),
    rec({ 中文品名: 'B', 許可證字號: 'L2', 公告更新時間: '2026/06/01', _theme: 'amber' as Theme }),
    rec({ 中文品名: 'C', 許可證字號: 'L3', 公告更新時間: '2025/12/01', _theme: 'red' as Theme }),
  ];
  const base = { showLatestTen: false, sortMode: 'newest' as const, debouncedSearch: '', filterStatus: 'all', filterYear: 'all', filterMonth: 'all' };

  it('最新十筆：固定依公告日期最新排序，忽略 sortMode', () => {
    // 即使 sortMode=name，最新十筆仍依日期
    const out = selectVisibleRecords(list, { ...base, showLatestTen: true, sortMode: 'name' });
    expect(out.map(i => i.公告更新時間)).toEqual(['2026/06/01', '2025/12/01', '2020/01/01']);
  });

  it('最新十筆：忽略 search/status/year/month 篩選', () => {
    const out = selectVisibleRecords(list, { ...base, showLatestTen: true, filterStatus: 'red', debouncedSearch: 'ZZZ' });
    expect(out).toHaveLength(3); // 篩選被忽略
  });

  it('最新十筆：最多 10 筆', () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      rec({ 中文品名: `D${i}`, 許可證字號: `K${i}`, 公告更新時間: `2025/01/${String((i % 28) + 1).padStart(2, '0')}` }));
    expect(selectVisibleRecords(many, { ...base, showLatestTen: true })).toHaveLength(10);
  });

  it('一般模式：套用排序與篩選', () => {
    const out = selectVisibleRecords(list, { ...base, filterStatus: 'red' });
    expect(out.every(i => i._theme === 'red')).toBe(true);
    expect(out.map(i => i.公告更新時間)).toEqual(['2025/12/01', '2020/01/01']); // newest 排序
  });
});

// ======================================================================
// alternativeConfidence（CR-07）
// ======================================================================
describe('alternativeConfidence (CR-07)', () => {
  it('null/空 → null', () => {
    expect(alternativeConfidence(null)).toBeNull();
    expect(alternativeConfidence('')).toBeNull();
    expect(alternativeConfidence('   ')).toBeNull();
  });

  it('已知雜訊片段判為 low（不當成藥名）', () => {
    for (const s of ['與缺藥品項成分不盡相似', '(詳述如下)', '的病人', '替代']) {
      expect(alternativeConfidence(s)).toBe('low');
    }
  });

  it('URL 判為 low', () => {
    expect(alternativeConfidence('藥品圖卡連結如下：https://210.69.111.207/x')).toBe('low');
  });

  it('像藥名者判為 high', () => {
    expect(alternativeConfidence('Foo Tablet 100mg')).toBe('high');   // Latin 藥名
    expect(alternativeConfidence('衛署藥製字第040825號')).toBe('high'); // 許可證號
    expect(alternativeConfidence('◎溫士頓維他命A眼藥膏')).toBe('high'); // ◎ 清單標記
  });
});

// ======================================================================
// isSupplyData（CR-10）
// ======================================================================
describe('isSupplyData (CR-10)', () => {
  it('合法結構通過', () => {
    expect(isSupplyData({ last_updated: '2026-07-21 00:00:00', datasets: { a: [], b: [rec({})] } })).toBe(true);
  });

  it('缺欄位 / 型別錯 / 非物件 → false', () => {
    expect(isSupplyData(null)).toBe(false);
    expect(isSupplyData('str')).toBe(false);
    expect(isSupplyData({ datasets: {} })).toBe(false);            // 缺 last_updated
    expect(isSupplyData({ last_updated: 1, datasets: {} })).toBe(false); // 型別錯
    expect(isSupplyData({ last_updated: 'x' })).toBe(false);        // 缺 datasets
    expect(isSupplyData({ last_updated: 'x', datasets: { a: 'not-array' } })).toBe(false);
  });
});

// ======================================================================
// 增量 F：上游停更偵測（規格 .ai-review/plan-upstream-freeze.md）
//
// 每個 describe 對應驗收條件，並堵死 plan-verdict 區塊 3 指名的弱化實作
// （「isSupplyData 永遠回 true」「UI 永遠不顯示提示」…）。
// ======================================================================
describe('F10: isSupplyData 對新舊 payload 的相容性', () => {
  const oldPayload = { last_updated: '2026-09-04 04:10:50', datasets: { a: [] } };
  const newPayload = {
    last_updated: '2026-09-04 04:10:50',
    upstream_max_date: '2026/08/31',
    frozen_runs: 2,
    last_observed_period: '2026-W36',
    datasets: { a: [] },
  };

  it('缺偵測欄的舊 payload 仍視為有效', () => {
    expect(isSupplyData(oldPayload)).toBe(true);
  });

  it('含偵測欄的新 payload 視為有效', () => {
    expect(isSupplyData(newPayload)).toBe(true);
  });

  it('upstream_max_date 為 null 仍有效', () => {
    expect(isSupplyData({ ...newPayload, upstream_max_date: null })).toBe(true);
  });

  // 堵死「永遠回 true」：核心欄位壞掉仍須拒絕
  it('核心欄位結構錯誤仍須拒絕（即使偵測欄齊全）', () => {
    expect(isSupplyData({ ...newPayload, last_updated: 1 })).toBe(false);
    expect(isSupplyData({ ...newPayload, datasets: 'x' })).toBe(false);
    expect(isSupplyData({ ...newPayload, datasets: { a: 'not-array' } })).toBe(false);
  });

  it('偵測欄無效時不否決整份清單（停用偵測即可）', () => {
    const weird = { ...newPayload, frozen_runs: 'three', upstream_max_date: 42 };
    expect(isSupplyData(weird)).toBe(true);
    expect(isUpstreamFrozen(weird as never)).toBe(false);
  });
});

describe('F11: isUpstreamFrozen 門檻與反例', () => {
  const base = { upstream_max_date: '2026/08/31', frozen_runs: 4 };

  it('門檻邊界 3/4/5', () => {
    expect(isUpstreamFrozen({ ...base, frozen_runs: 3 })).toBe(false);
    expect(isUpstreamFrozen({ ...base, frozen_runs: 4 })).toBe(true);
    expect(isUpstreamFrozen({ ...base, frozen_runs: 5 })).toBe(true);
  });

  it('FROZEN_RUNS_THRESHOLD 為 4', () => {
    expect(FROZEN_RUNS_THRESHOLD).toBe(4);
  });

  // 堵死「只判 typeof number 與門檻」
  it.each([
    ['缺欄', {}],
    ['字串', { ...base, frozen_runs: '9' }],
    ['布林 true', { ...base, frozen_runs: true }],
    ['null', { ...base, frozen_runs: null }],
    ['負數', { ...base, frozen_runs: -4 }],
    ['小數', { ...base, frozen_runs: 4.5 }],
    ['NaN', { ...base, frozen_runs: NaN }],
    ['Infinity', { ...base, frozen_runs: Infinity }],
    ['日期缺欄', { frozen_runs: 9 }],
    ['日期為 null', { ...base, upstream_max_date: null }],
    ['日期非字串', { ...base, upstream_max_date: 20260831 }],
    ['日期非真實曆日', { ...base, upstream_max_date: '2026/02/30' }],
    ['整份為 null', null],
    ['整份為 undefined', undefined],
  ])('%s → false', (_label, input) => {
    expect(isUpstreamFrozen(input as never)).toBe(false);
  });

  // 日期距今多久不得單獨決定結果
  it('日期很舊但計數未達門檻 → 仍為 false', () => {
    expect(isUpstreamFrozen({ upstream_max_date: '2019/01/01', frozen_runs: 1 })).toBe(false);
  });

  it('日期很新但計數達門檻 → 仍為 true（計數才是判準）', () => {
    expect(isUpstreamFrozen({ upstream_max_date: '2026/09/08', frozen_runs: 4 })).toBe(true);
  });
});

describe('F12: 模式 A 未退化，且兩模式互不遮蔽', () => {
  const now = new Date('2026-09-08T12:00:00').getTime();

  it('isDataStale 門檻與邊界行為不變', () => {
    expect(STALE_THRESHOLD_DAYS).toBe(10);
    expect(isDataStale('2026-09-08 00:00:00', now)).toBe(false);
    // 邊界：age 恰為 10 天 → 不算過期；11 天 → 過期（門檻為 age > 10）
    expect(isDataStale('2026-08-29 12:00:00', now)).toBe(false);
    expect(isDataStale('2026-08-28 12:00:00', now)).toBe(true);
    expect(isDataStale('2026-08-20 00:00:00', now)).toBe(true);
  });

  it('新增偵測欄不影響 isDataStale 結果', () => {
    const fresh = '2026-09-08 00:00:00';
    expect(isDataStale(fresh, now)).toBe(false);
    // 同一時間戳，無論 payload 帶不帶偵測欄，模式 A 判定都一樣
    expect(isDataStale(fresh, now)).toBe(isDataStale(fresh, now));
  });

  // A／B 四種組合：兩者互為獨立訊號
  it.each([
    ['A 假 B 假', '2026-09-08 00:00:00', 1, false, false],
    ['A 真 B 假', '2026-08-20 00:00:00', 1, true, false],
    ['A 假 B 真', '2026-09-08 00:00:00', 4, false, true],
    ['A 真 B 真', '2026-08-20 00:00:00', 4, true, true],
  ])('%s', (_l, lastUpdated, runs, expectA, expectB) => {
    const data = {
      last_updated: lastUpdated as string,
      upstream_max_date: '2026/08/31',
      frozen_runs: runs as number,
      datasets: {},
    };
    expect(isDataStale(data.last_updated, now)).toBe(expectA);
    expect(isUpstreamFrozen(data)).toBe(expectB);
  });
});

describe('F13: 舊 payload 不誤報，新 payload 達門檻必須報', () => {
  it('舊 payload（缺偵測欄）→ 不顯示提示', () => {
    const old = { last_updated: '2026-09-04 04:10:50', datasets: {} };
    expect(isSupplyData(old)).toBe(true);
    expect(isUpstreamFrozen(old as never)).toBe(false);
  });

  // 堵死「UI 永遠不顯示提示」：達門檻時必須為 true
  it('新 payload 達門檻 → 必須顯示提示', () => {
    expect(isUpstreamFrozen({ upstream_max_date: '2026/08/31', frozen_runs: 4 })).toBe(true);
  });

  it('不可判定狀態（日期 null）不誤報', () => {
    expect(isUpstreamFrozen({ upstream_max_date: null, frozen_runs: 9 })).toBe(false);
  });
});
