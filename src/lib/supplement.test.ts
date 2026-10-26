import { describe, it, expect } from 'vitest';
import { cleanSupplyData, type DrugRecord, type SupplyData } from './dataPipeline';
import {
  applySupplement,
  isSupplementData,
  isValidAnnouncementDate,
  loadSupplement,
  normalizeKey,
  recordKeys,
  supplementAgeDays,
  supplementListUrl,
  trustExpiresAt,
  CATEGORY_META,
  type CategoryKey,
  type SupersedeEntry,
  type SupplementCategory,
  type SupplementData,
  type SupplementLoad,
} from './supplement';

// ----------------------------------------------------------------------
// 增量 S（plan-supplement.md §7 B1–B9）。共用情境與 Python 端讀同一份
// scripts/fixtures/supplement_cases.json，兩端各自對照獨立寫定的期望。
// ----------------------------------------------------------------------
interface SharedCase {
  name: string;
  category: CategoryKey;
  main: DrugRecord[];
  site: DrugRecord[];
  expected: { error: boolean; additions?: string[]; supersedes?: SupersedeEntry[] };
  display: string[];
  cleaned: string[];
}
interface SharedFixture { normalize: [string, string][]; cases: SharedCase[] }

const SHARED = Object.values(
  import.meta.glob('../../scripts/fixtures/supplement_cases.json', { eager: true, import: 'default' }),
)[0] as SharedFixture;

const NOW = Date.parse('2026-10-26T09:30:00+08:00');
const MAIN_UPDATED = '2026-10-23 04:53:03';
const RUN = '20261026T091000-abcd';
const DAY = 86400000;

function mkMain(datasets: Record<string, DrugRecord[]> = {}, lastUpdated = MAIN_UPDATED): SupplyData {
  return {
    last_updated: lastUpdated,
    upstream_max_date: '2026/10/07',
    frozen_runs: 1,
    datasets: { '54504_with_alternative': [], '54505_no_alternative': [], '54506_resolved': [], ...datasets },
  };
}

function mkCat(key: CategoryKey, o: Partial<SupplementCategory> = {}): SupplementCategory {
  return {
    dataset: CATEGORY_META[key].dataset,
    state: 'ok',
    error: null,
    last_success_at: '2026-10-26T09:10:00+08:00',
    success_run_id: RUN,
    base: { last_updated: MAIN_UPDATED, upstream_max_date: '2026/10/07' },
    additions: [],
    supersedes: [],
    ...o,
  };
}

function mkSup(cats: Partial<Record<CategoryKey, Partial<SupplementCategory>>> = {}): SupplementLoad {
  const data: SupplementData = {
    schema: 1,
    generated_at: '2026-10-26T09:10:00+08:00',
    run_id: RUN,
    categories: { s3: mkCat('s3', cats.s3), s4: mkCat('s4', cats.s4), s2: mkCat('s2', cats.s2) },
  };
  return { status: 'ok', data };
}

function od(no: string, date: string, zh: string, license = '衛署藥製字第000001號', text = '說明', en = 'EN'): DrugRecord {
  return { 編號: no, 公告更新時間: date, 中文品名: `${zh}\n${en}`, 許可證字號: license, 供應狀態: text };
}

function dsms(caseNo: string, date: string, zh: string, license = '衛署藥製字第000001號', text = '說明', en = 'EN'): DrugRecord {
  return { ...od(`dsms-${caseNo}`, date, zh, license, text, en), _來源: 'dsms', _案件編號: caseNo };
}

function sup(row: DrugRecord, compareContent = true): SupersedeEntry {
  return {
    品名鍵: normalizeKey(row.中文品名.split('\n')[0]),
    公告更新時間: row.公告更新時間,
    許可證字號: row.許可證字號,
    指紋: compareContent ? normalizeKey(row.供應狀態) : null,
  };
}

const ids = (rows: DrugRecord[]) => rows.map(r => r.編號);
const visible = (data: SupplyData) => cleanSupplyData(data).all.map(r => `${r._theme}:${r.編號}`);

// ----------------------------------------------------------------------
describe('normalizeKey：與 Python 共用向量', () => {
  it.each(SHARED.normalize)('%j → %j', (raw, expected) => {
    expect(normalizeKey(raw)).toBe(expected);
  });
});

describe('B1：共用情境（三類皆 ok、同一次執行、新鮮）', () => {
  for (const c of SHARED.cases) {
    it(c.name, () => {
      const dataset = CATEGORY_META[c.category].dataset;
      const main = mkMain({ [dataset]: c.main });
      const before = JSON.stringify(main);
      const load = c.expected.error
        ? mkSup({ [c.category]: { state: 'error', error: '測試', last_success_at: null, success_run_id: null, base: null } })
        : mkSup({ [c.category]: {
            additions: c.site.filter(r => c.expected.additions!.includes(r.編號)),
            supersedes: c.expected.supersedes!,
          } });
      const loadBefore = JSON.stringify(load);
      const r1 = applySupplement(main, load, NOW);
      expect(ids(r1.data.datasets[dataset])).toEqual(c.display);
      expect(r1.trusted).toBe(!c.expected.error);
      // 清洗後（T4）：編號序列等於獨立寫定的期望，且每一列內容就是來源那一列（不是錯配到別列）
      const cleaned = cleanSupplyData(r1.data).all;
      expect(ids(cleaned)).toEqual(c.cleaned);
      const source = new Map([...c.main, ...c.site].map(r => [r.編號, r]));
      for (const row of cleaned) {
        expect(row.供應狀態).toBe(source.get(row.編號)!.供應狀態);
        expect(row.許可證字號).toBe(source.get(row.編號)!.許可證字號);
      }
      // 確定性：相同輸入、相同結果；主檔與補抓輸入都不被修改
      expect(applySupplement(main, load, NOW).data).toEqual(r1.data);
      expect(JSON.stringify(main)).toBe(before);
      expect(JSON.stringify(load)).toBe(loadBefore);
    });
  }
});

// ----------------------------------------------------------------------
describe('B2：s3→s2 移類與既有 zombie 規則', () => {
  const L1 = '衛署藥輸字第000900號';
  const X = od('X', '2026/10/01', 'X藥', L1, 'X缺藥');
  const W = od('W', '2026/09/01', 'W藥', L1, 'W缺藥');
  const V = od('V', '2026/10/25', 'V藥', L1, 'V缺藥');
  const U = od('U', '2026/09/01', 'U藥', '衛署藥輸字第000999號', 'U缺藥');
  const main = mkMain({ '54504_with_alternative': [X, W, V, U] });
  const xResolved = dsms('1150900', '2026/10/20', 'X藥', L1, 'X已恢復');

  it('三類同一次執行皆 ok：X 只在已恢復；W 依 N2 被隱藏（本增量沿用既有規則並明確接受）；V、U 仍在', () => {
    const r = applySupplement(main, mkSup({ s3: { supersedes: [sup(X)] }, s2: { additions: [xResolved] } }), NOW);
    expect(visible(r.data).sort()).toEqual(['amber:U', 'amber:V', 'emerald:dsms-1150900'].sort());
  });

  it('反例：s2 error 但沿用非空的恢復 additions → 不套用，X 與 W 都仍在有替代', () => {
    const r = applySupplement(main, mkSup({
      s3: { supersedes: [sup(X)] },
      s2: { state: 'error', error: '逾時', additions: [xResolved] },
    }), NOW);
    expect(r.trusted).toBe(false);
    expect(visible(r.data).sort()).toEqual(['amber:U', 'amber:V', 'amber:W', 'amber:X'].sort());
  });

  it('反例：X 移到 s4、s4 error → X 仍在有替代', () => {
    const r = applySupplement(main, mkSup({
      s3: { supersedes: [sup(X)] },
      s4: { state: 'error', error: '壞', last_success_at: null, success_run_id: null, base: null },
    }), NOW);
    expect(visible(r.data)).toContain('amber:X');
  });
});

describe('B3：修訂', () => {
  it('改日期：只留新版，徽章連到官網列表', () => {
    const old = od('O1', '2026/05/07', '滅必治軟膠囊50毫克');
    const fresh = dsms('1141284', '2026/10/16', '滅必治軟膠囊50毫克', '衛署藥製字第000001號', '新說明');
    const other = od('O2', '2025/01/02', '滅必治軟膠囊50毫克');               // 同名另一次公告
    const y = od('O3', '2026/05/07', '滅必治軟膠囊50毫克', '衛署藥製字第000002號'); // 同日期不同證號
    const r = applySupplement(mkMain({ '54504_with_alternative': [old, other, y] }),
      mkSup({ s3: { supersedes: [sup(old)], additions: [fresh] } }), NOW);
    const rows = cleanSupplyData(r.data).all;
    expect(rows.map(x => x.編號).sort()).toEqual(['O2', 'O3', 'dsms-1141284'].sort());
    const card = rows.find(x => x.編號 === 'dsms-1141284')!;
    expect(card.供應狀態).toBe('新說明');
    expect(supplementListUrl(card)).toBe('https://dsms.fda.gov.tw/DrugList.aspx?s=3');
    expect(supplementListUrl(rows.find(x => x.編號 === 'O2')!)).toBeNull();
  });

  it('同日期只改文字：只留 B', () => {
    const a = od('O1', '2026/10/07', '可嗽平錠', '衛署藥製字第040794號', '替代：甲');
    const b = dsms('1150570', '2026/10/07', '可嗽平錠', '衛署藥製字第040794號', '替代：乙');
    const r = applySupplement(mkMain({ '54504_with_alternative': [a] }),
      mkSup({ s3: { supersedes: [sup(a)], additions: [b] } }), NOW);
    const rows = cleanSupplyData(r.data).all;
    expect(ids(rows)).toEqual(['dsms-1150570']);
    expect(rows[0].供應狀態).toBe('替代：乙');
    expect(rows[0]._altText).toBe(cleanSupplyData(mkMain({ '54504_with_alternative': [b] })).all[0]._altText);
  });

  it('D10 不成立：A 與 B 並列，紅色文案寫明新舊並列', () => {
    const a = od('O1', '2026/10/07', '可嗽平錠', '衛署藥製字第040794號', '替代：甲');
    const b = dsms('1150570', '2026/10/07', '可嗽平錠', '衛署藥製字第040794號', '替代：乙');
    const r = applySupplement(mkMain({ '54504_with_alternative': [a] }),
      mkSup({ s3: { supersedes: [sup(a)], additions: [b] }, s2: { state: 'error', error: '壞' } }), NOW);
    expect(ids(r.data.datasets['54504_with_alternative'])).toEqual(['O1', 'dsms-1150570']);
    expect(r.warnings.join('')).toContain('新舊版本並列，供應說明請以官網為準');
  });
});

// ----------------------------------------------------------------------
describe('B4：橫幅狀態', () => {
  const main = mkMain();
  const text = (load: SupplementLoad, m = main) => applySupplement(m, load, NOW);

  it('補抓檔載入失敗 → 紅，主資料不變', () => {
    const r = text({ status: 'error', reason: 'HTTP 404' });
    expect(r.warnings[0]).toContain('無法載入公告頁補抓資料（HTTP 404）');
    expect(r.warnings[0]).toContain('切勿據此判定「沒有新缺藥」');
    expect(r.data).toBe(main);
  });

  it('單類 error → 指名類別；沒有差異時紅色也不消失', () => {
    const r = text(mkSup({ s2: { state: 'error', error: '逾時', additions: [], supersedes: [] } }));
    expect(r.warnings.some(w => w.includes('「已恢復」類補抓失敗（逾時）'))).toBe(true);
    expect(r.info).toBeNull();
  });

  it('多種紅色並列，全部出現', () => {
    const r = text(mkSup({
      s3: { state: 'error', error: '改版' },
      s4: { last_success_at: new Date(NOW - 4 * DAY).toISOString() },
      s2: { base: { last_updated: '2026-10-30 00:00:00', upstream_max_date: null } },
    }));
    const all = r.warnings.join('\n');
    expect(all).toContain('「有替代」類補抓失敗（改版）');
    expect(all).toContain('「無替代」類補抓資料已 4 天未更新');
    expect(all).toContain('「已恢復」類補抓資料比目前載入的主資料新（版本不一致）');
  });

  it('全部 ok、有差異 → 琥珀資訊；沒有差異 → 不顯示任何橫幅', () => {
    const withDiff = text(mkSup({ s3: { additions: [dsms('1', '2026/10/21', '新藥')] } }));
    expect(withDiff.warnings).toEqual([]);
    expect(withDiff.info).toContain('表中 1 筆較新公告');
    const none = text(mkSup());
    expect(none.warnings).toEqual([]);
    expect(none.info).toBeNull();
  });
});

describe('B5：新鮮度（按類別）', () => {
  const at = (ms: number) => new Date(ms).toISOString();
  it.each([
    [2.9, false], [3.0, false], [3.1, true],
  ])('%s 天前 → 紅：%s', (days, red) => {
    const r = applySupplement(mkMain(), mkSup({ s3: { last_success_at: at(NOW - days * DAY) } }), NOW);
    expect(r.warnings.some(w => w.includes('「有替代」類補抓資料已'))).toBe(red);
  });

  it('跨午夜：前一天 23:59 → 不紅', () => {
    const now = Date.parse('2026-10-27T00:01:00+08:00');
    expect(supplementAgeDays('2026-10-26T23:59:00+08:00', now)).toBeLessThan(1);
  });

  it.each([['不是日期'], [null], ['2026-10-26T12:00:00+08:00']])('last_success_at=%j → 紅、不隱藏', v => {
    const x = od('O1', '2026/05/07', 'X藥');
    const r = applySupplement(mkMain({ '54504_with_alternative': [x] }),
      mkSup({ s3: { last_success_at: v as string | null, supersedes: [sup(x)] } }), NOW);
    expect(r.warnings.some(w => w.includes('「有替代」類補抓更新時間不明'))).toBe(true);
    expect(ids(r.data.datasets['54504_with_alternative'])).toEqual(['O1']);
  });

  it('時鐘偏差容許量內的未來時間仍有效', () => {
    expect(supplementAgeDays(new Date(NOW + 60_000).toISOString(), NOW)).toBe(0);
  });

  it('generated_at 是今天，但某類 last_success_at 是 4 天前 → 該類紅', () => {
    const r = applySupplement(mkMain(), mkSup({ s2: { last_success_at: at(NOW - 4 * DAY) } }), NOW);
    expect(r.warnings.some(w => w.includes('「已恢復」類補抓資料已 4 天未更新'))).toBe(true);
    expect(r.trusted).toBe(false);
  });
});

describe('R4：頁面常駐跨過新鮮度門檻', () => {
  const x = od('O1', '2026/05/07', 'X藥');
  const main = mkMain({ '54504_with_alternative': [x] });
  const loadedAt = Date.parse('2026-10-26T09:10:00+08:00');
  const load = mkSup({ s3: { supersedes: [sup(x)], additions: [dsms('1', '2026/10/16', 'X藥', '衛署藥製字第000001號', '新')] } });

  it('信任到期時刻 = 最早的 last_success_at + 3 天', () => {
    expect(trustExpiresAt(load, loadedAt)).toBe(loadedAt + 3 * DAY);
    expect(trustExpiresAt({ status: 'error', reason: 'x' }, loadedAt)).toBeNull();
    expect(trustExpiresAt(load, loadedAt + 4 * DAY)).toBeNull();   // 已過期 → 不再排程
  });

  it('同一份資料，到期前隱藏舊版；到期後（不重新載入）改為紅色、舊版重新出現', () => {
    const before = applySupplement(main, load, loadedAt + 2.9 * DAY);
    expect(before.trusted).toBe(true);
    expect(ids(before.data.datasets['54504_with_alternative'])).toEqual(['dsms-1']);
    const expires = trustExpiresAt(load, loadedAt + 2.9 * DAY)!;
    const after = applySupplement(main, load, expires + 1000);   // App 在到期後 1 秒重算
    expect(after.trusted).toBe(false);
    expect(after.warnings.some(w => w.includes('已 3 天未更新'))).toBe(true);
    expect(ids(after.data.datasets['54504_with_alternative'])).toEqual(['O1', 'dsms-1']);
  });

  it('多類別取最早到期者', () => {
    const mixed = mkSup({ s2: { last_success_at: '2026-10-25T09:10:00+08:00' } });
    expect(trustExpiresAt(mixed, loadedAt)).toBe(Date.parse('2026-10-25T09:10:00+08:00') + 3 * DAY);
  });
});

// ----------------------------------------------------------------------
describe('B6：補抓檔異常不阻斷主資料', () => {
  const main = mkMain({ '54504_with_alternative': [od('O1', '2026/10/01', '甲藥'), od('O2', '2026/09/01', '乙藥')] });
  const res = (status: number, body: unknown) => ({
    ok: status >= 200 && status < 300, status, json: async () => body,
  }) as Response;
  const cases: [string, typeof fetch][] = [
    ['reject', (async () => { throw new TypeError('Failed to fetch'); }) as typeof fetch],
    ['500', (async () => res(500, {})) as typeof fetch],
    ['JSON 壞', (async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('bad'); } }) as unknown as Response) as typeof fetch],
    ['schema 不符', (async () => res(200, { schema: 2 })) as typeof fetch],
    ['pending', (() => new Promise<Response>(() => {})) as typeof fetch],
  ];
  it.each(cases)('%s → error；顯示內容等於只有主檔經清洗的結果', async (_name, fetchImpl) => {
    const load = await loadSupplement('x', fetchImpl, 30);
    expect(load.status).toBe('error');
    const r = applySupplement(main, load, NOW);
    expect(cleanSupplyData(r.data)).toEqual(cleanSupplyData(main));
    expect(r.warnings).toHaveLength(1);
  });

  it('JSON 壞的錯誤訊息不外露解析細節', async () => {
    const load = await loadSupplement('x', cases[2][1], 30);
    expect(load).toEqual({ status: 'error', reason: '回應不是 JSON' });
  });

  it('合法補抓檔 → ok', async () => {
    const good = (mkSup() as { data: SupplementData }).data;
    const load = await loadSupplement('x', (async () => res(200, good)) as typeof fetch, 30);
    expect(load.status).toBe('ok');
  });
});

describe('B7：計數等於最終顯示集合', () => {
  it('被隱藏、被既有清洗移除的列都不計', () => {
    const old = od('O1', '2026/05/07', 'X藥');
    const resolvedSameLicense = od('R1', '2026/06/01', 'Z藥', '衛署藥製字第000777號');
    const zombie = od('O2', '2026/05/01', 'Z藥', '衛署藥製字第000777號');
    const main = mkMain({ '54504_with_alternative': [old, zombie], '54506_resolved': [resolvedSameLicense] });
    const r = applySupplement(main, mkSup({
      s3: { supersedes: [sup(old)], additions: [dsms('9', '2026/10/16', 'X藥'), dsms('10', '2026/10/21', 'Y藥')] },
    }), NOW);
    const cleaned = cleanSupplyData(r.data);
    expect(cleaned.withAlt).toBe(cleaned.all.filter(x => x._theme === 'amber').length);
    expect(cleaned.all.filter(x => x._theme === 'amber').map(x => x.編號).sort()).toEqual(['dsms-10', 'dsms-9']);
    expect(cleaned.resolved).toBe(1);
  });
});

// ----------------------------------------------------------------------
describe('B8：隱藏的安全條件（D10）', () => {
  const x = od('O1', '2026/05/07', 'X藥');
  const w = od('O2', '2026/09/01', 'W藥', '衛署藥製字第000888號');
  const main = mkMain({ '54504_with_alternative': [x, w] });
  const diff = {
    s3: { supersedes: [sup(x)], additions: [dsms('1', '2026/10/16', 'X藥', '衛署藥製字第000001號', '新')] },
    s2: { additions: [dsms('2', '2026/10/20', 'W藥', '衛署藥製字第000888號', '已恢復')] },
  };
  const mainOnly = new Set(visible(main));

  it.each<[string, Partial<Record<CategoryKey, Partial<SupplementCategory>>>, string]>([
    ['success_run_id 不同', { s4: { success_run_id: 'OTHER' } }, MAIN_UPDATED],
    ['某類 error', { s4: { state: 'error', error: '壞' } }, MAIN_UPDATED],
    ['某類過期', { s4: { last_success_at: new Date(NOW - 5 * DAY).toISOString() } }, MAIN_UPDATED],
    ['主檔比 base 舊', {}, '2026-10-16 04:00:00'],
  ])('%s → 不隱藏、不加 s2，s3 additions 照常', (_name, override, mainUpdated) => {
    const m = mkMain(main.datasets, mainUpdated);
    const r = applySupplement(m, mkSup({ ...diff, ...override, s3: { ...diff.s3, ...override.s3 } }), NOW);
    const shown = new Set(visible(r.data));
    for (const v of visible(m)) expect(shown.has(v) || !mainOnly.has(v)).toBe(true);
    expect(shown.has('amber:O1') && shown.has('amber:O2')).toBe(true);
    expect(shown.has('amber:dsms-1')).toBe(true);
    expect(shown.has('emerald:dsms-2')).toBe(false);
    expect(r.trusted).toBe(false);
  });

  it('正例：條件都成立才隱藏、才加入 s2', () => {
    const r = applySupplement(main, mkSup(diff), NOW);
    expect(visible(r.data).sort()).toEqual(['amber:dsms-1', 'emerald:dsms-2'].sort());
  });

  it('已接受的限制：主檔較新且重新出現同單位 → 仍隱藏；指紋不同 → 不隱藏', () => {
    const newer = mkMain(main.datasets, '2026-10-26 04:00:00');
    expect(ids(applySupplement(newer, mkSup({ s3: { supersedes: [sup(x)] } }), NOW)
      .data.datasets['54504_with_alternative'])).toEqual(['O2']);
    const changed = mkMain({ '54504_with_alternative': [{ ...x, 供應狀態: '主檔已更正' }, w] }, '2026-10-26 04:00:00');
    expect(ids(applySupplement(changed, mkSup({ s3: { supersedes: [sup(x)] } }), NOW)
      .data.datasets['54504_with_alternative'])).toEqual(['O1', 'O2']);
  });

  it.each<[string, SupplementCategory['base']]>([
    ['base 為 null', null],
    ['base.last_updated 為 null', { last_updated: null, upstream_max_date: null }],
    ['base.last_updated 無法解析', { last_updated: 'bad', upstream_max_date: null }],
  ])('R1：成功類別的基準版本不明（%s）→ 紅、不隱藏、不加 s2', (_n, base) => {
    const r = applySupplement(main, mkSup({ ...diff, s4: { base } }), NOW);
    expect(r.trusted).toBe(false);
    expect(r.warnings.some(w => w.includes('「無替代」類補抓資料的比對基準版本不明'))).toBe(true);
    expect(ids(r.data.datasets['54504_with_alternative'])).toContain('O1');
    expect(ids(r.data.datasets['54506_resolved'])).not.toContain('dsms-2');
  });

  it('R1：主檔 last_updated 無法解析 → 不可信', () => {
    const r = applySupplement(mkMain(main.datasets, 'garbage'), mkSup(diff), NOW);
    expect(r.trusted).toBe(false);
  });

  it('R1：首次就失敗、沒有任何結果的類別，不重複報「基準不明」', () => {
    const r = applySupplement(main, mkSup({
      s4: { state: 'error', error: '壞', last_success_at: null, success_run_id: null, base: null },
    }), NOW);
    expect(r.warnings.filter(w => w.includes('「無替代」'))).toEqual(['「無替代」類補抓失敗（壞），沒有可用的補抓結果。']);
  });

  it('主檔品名結構不支援的列永不被隱藏', () => {
    const odd = { ...x, 中文品名: 'X藥' };
    const r = applySupplement(mkMain({ '54504_with_alternative': [odd] }),
      mkSup({ s3: { supersedes: [{ ...sup(x), 品名鍵: 'X藥' }] } }), NOW);
    expect(ids(r.data.datasets['54504_with_alternative'])).toEqual(['O1']);
  });
});

describe('B9：卡片身分', () => {
  const a = { ...od('1', '2026/10/07', '同證藥', '衛署藥製字第000001號', '內容A'), _theme: 'amber' as const };
  const b = { ...od('2', '2026/10/07', '同證藥', '衛署藥製字第000001號', '內容B'), _theme: 'amber' as const };
  const c = { ...od('3', '2026/09/01', '別的藥'), _theme: 'amber' as const };

  it('同證、同日期、不同內容 → key 不同；完全相同的兩列也不撞 key', () => {
    const keys = recordKeys([a, b, a]);
    expect(new Set(keys).size).toBe(3);
  });

  it('重新排序、插入新列 → 同一列的 key 不變（不依賴位置或「編號」）', () => {
    const k1 = recordKeys([a, b]);
    const k2 = recordKeys([c, b, { ...a, 編號: '999' }]);
    expect(k2[2]).toBe(k1[0]);
    expect(k2[1]).toBe(k1[1]);
  });

  it('內容改變 → key 改變（展開狀態不會轉移到另一列）', () => {
    expect(recordKeys([{ ...a, 供應狀態: '更正後' }])[0]).not.toBe(recordKeys([a])[0]);
  });
});

describe('R2／T6：污染的補抓檔經正式入口被拒，缺藥列保留', () => {
  // Codex 重現的攻擊路徑：把主檔一筆缺藥偽造成 s2 恢復公告（未來日期、非法案件編號、錯誤編號），
  // 原本會通過驗證，經既有 zombie 規則把缺藥列藏掉。
  const shortage = od('O1', '2026/10/01', 'X藥', '衛署藥輸字第000900號', '缺藥中');
  const main = mkMain({ '54504_with_alternative': [shortage] });
  const fake = (patch: Partial<DrugRecord> & Record<string, unknown>) =>
    ({ ...dsms('1150900', '2026/10/20', 'X藥', '衛署藥輸字第000900號', '已恢復'), ...patch }) as DrugRecord;
  const res = (body: unknown) => (async () => ({ ok: true, status: 200, json: async () => body }) as Response) as typeof fetch;
  const fileWith = (cats: Partial<Record<CategoryKey, Partial<SupplementCategory>>>) =>
    (mkSup(cats) as { data: SupplementData }).data;

  it.each<[string, SupplementData]>([
    ['未來日期 2099/01/01', fileWith({ s2: { additions: [fake({ 公告更新時間: '2099/01/01' })] } })],
    ['明天之後（台灣時間 +2 天）', fileWith({ s2: { additions: [fake({ 公告更新時間: '2026/10/28' })] } })],
    ['日期格式 YYYY/M', fileWith({ s2: { additions: [fake({ 公告更新時間: '2026/10' })] } })],
    ['案件編號非數字', fileWith({ s2: { additions: [fake({ _案件編號: 'not-a-number', 編號: 'dsms-not-a-number' })] } })],
    ['編號與案件編號不對應', fileWith({ s2: { additions: [fake({ 編號: 'wrong-id' })] } })],
    ['證號格式錯', fileWith({ s2: { additions: [fake({ 許可證字號: '藥字第1號' })] } })],
    ['supersede 日期格式錯', fileWith({ s3: { supersedes: [{ ...sup(shortage), 公告更新時間: '2026/10/1' }] } })],
    ['s3 supersede 沒有指紋', fileWith({ s3: { supersedes: [{ ...sup(shortage), 指紋: null }] } })],
    ['s2 supersede 帶指紋', fileWith({ s2: { supersedes: [{ ...sup(shortage, false), 指紋: 'x' }] } })],
    ['state ok 卻有 error 訊息', fileWith({ s2: { error: '其實失敗了' } })],
    ['沒有成功紀錄卻帶有結果', fileWith({ s2: { state: 'error', error: 'x', last_success_at: null,
      success_run_id: null, base: null, additions: [fake({})] } })],
  ])('%s → 整份拒收、紅色、缺藥列仍在', async (_n, file) => {
    const load = await loadSupplement('x', res(file), 30, NOW);
    expect(load.status).toBe('error');
    const r = applySupplement(main, load, NOW);
    expect(visible(r.data)).toEqual(['amber:O1']);
    expect(r.warnings[0]).toContain('無法載入公告頁補抓資料');
  });

  it('對照組：合法的恢復公告經入口通過，且依既有規則生效', async () => {
    const load = await loadSupplement('x', res(fileWith({ s2: { additions: [fake({})] } })), 30, NOW);
    expect(load.status).toBe('ok');
    expect(visible(applySupplement(main, load, NOW).data)).toEqual(['emerald:dsms-1150900']);
  });

  it('台灣時間的「明天」上限：UTC 已過午夜也以台灣日期計', () => {
    const lateUtc = Date.parse('2026-10-26T23:30:00Z');   // 台灣 10/27 07:30
    expect(isValidAnnouncementDate('2026/10/28', lateUtc)).toBe(true);
    expect(isValidAnnouncementDate('2026/10/29', lateUtc)).toBe(false);
  });
});

describe('A10 跨端：Python 實際產出的「s2 失敗、沿用非空恢復公告」快照', () => {
  // scripts/fixtures/cross_s2_error_carried.json 由 Python 補抓程式實際產生；
  // pytest test_a10_cross_end_fixture_is_current 保證它與目前的 Python 產出一致。
  const CROSS = Object.values(
    import.meta.glob('../../scripts/fixtures/cross_s2_error_carried.json', { eager: true, import: 'default' }),
  )[0] as { main: SupplyData; supplement: unknown };
  const at = Date.parse('2026-10-26T10:30:00+08:00');

  it('通過前端逐筆驗證，但 D10 不成立：不套用恢復公告，V 仍在有替代', async () => {
    const load = await loadSupplement('x', (async () =>
      ({ ok: true, status: 200, json: async () => CROSS.supplement }) as Response) as typeof fetch, 30, at);
    expect(load.status).toBe('ok');
    const r = applySupplement(CROSS.main, load, at);
    expect(r.trusted).toBe(false);
    const visibleRows = cleanSupplyData(r.data).all;
    expect(visibleRows.map(x => `${x._theme}:${x.中文品名.split('\n')[0]}`)).toEqual(['amber:V藥']);
    expect(r.warnings.some(w => w.includes('「已恢復」類補抓失敗'))).toBe(true);
  });
});

describe('isSupplementData：逐筆驗證', () => {
  const good = (mkSup({ s3: { additions: [dsms('1', '2026/10/21', '新藥')] } }) as { data: SupplementData }).data;
  const broken = (mutate: (d: SupplementData) => void) => {
    const d = JSON.parse(JSON.stringify(good)) as SupplementData;
    mutate(d);
    return d;
  };
  it('合法 → true', () => expect(isSupplementData(good)).toBe(true));
  it.each<[string, (d: SupplementData) => void]>([
    ['缺類別', d => { delete (d.categories as Partial<Record<CategoryKey, SupplementCategory>>).s4; }],
    ['dataset 錯置', d => { d.categories.s3.dataset = '54506_resolved'; }],
    ['addition 缺證號', d => { d.categories.s3.additions[0].許可證字號 = ''; }],
    ['addition 日期無效', d => { d.categories.s3.additions[0].公告更新時間 = '2026/02/30'; }],
    ['addition 來源不是 dsms', d => { delete d.categories.s3.additions[0]._來源; }],
    ['supersede 指紋型別錯', d => { d.categories.s3.supersedes = [{ 品名鍵: 'x', 公告更新時間: '2026/01/01', 許可證字號: 'y', 指紋: 1 as unknown as string }]; }],
    ['state 非法', d => { (d.categories.s2 as unknown as { state: string }).state = 'partial'; }],
    ['base.last_updated 型別錯（R1：原本會讓 parseLastUpdated 拋例外）',
      d => { (d.categories.s3.base as unknown as { last_updated: number }).last_updated = 123; }],
    ['base 是字串', d => { (d.categories.s3 as unknown as { base: string }).base = 'x'; }],
  ])('%s → false', (_n, mutate) => expect(isSupplementData(broken(mutate))).toBe(false));
});
