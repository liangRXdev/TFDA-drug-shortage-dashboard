// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';
import type { DrugRecord, SupplyData } from './lib/dataPipeline';
import { normalizeKey, type SupplementData } from './lib/supplement';

// ----------------------------------------------------------------------
// App 層驗收（第二輪覆審 T-R2）：只測純函式時，刪掉 App 的計時器、focus／visibilitychange
// 接線、或不把 merged 傳給橫幅，測試仍會全綠。這裡渲染整個 App、以受控 fetch 與假時鐘
// 驗證 R4（常駐頁面隨時間撤銷信任）、B6（兩檔完成順序、補抓 pending）、B7（導覽計數）、
// B3（補抓徽章）。
// ----------------------------------------------------------------------
vi.mock('virtual:pwa-register/react', () => ({
  useRegisterSW: () => ({ needRefresh: [false, () => {}], updateServiceWorker: () => {} }),
}));
import App from './App';

const DAY = 86400000;
const NOW = Date.parse('2026-10-26T09:30:00+08:00');
const LICENSE = '衛署藥輸字第020882號';

function od(no: string, date: string, zh: string, text: string, license = LICENSE): DrugRecord {
  return { 編號: no, 公告更新時間: date, 中文品名: `${zh}\nEN`, 許可證字號: license, 供應狀態: text };
}

const OLD = od('O1', '2026/05/07', '滅必治軟膠囊50毫克', '舊說明');
const BACKGROUND = od('O2', '2026/09/01', '背景藥', '背景說明', '衛署藥製字第000001號');
const MAIN: SupplyData = {
  last_updated: '2026-10-23 04:53:03',
  upstream_max_date: '2026/10/07',
  frozen_runs: 0,
  datasets: { '54504_with_alternative': [OLD, BACKGROUND], '54505_no_alternative': [], '54506_resolved': [] },
};

function supplement(lastSuccessAt: string): SupplementData {
  const cat = (dataset: string) => ({
    dataset, state: 'ok' as const, error: null, last_success_at: lastSuccessAt, success_run_id: 'RUN',
    base: { last_updated: '2026-10-23 04:53:03', upstream_max_date: '2026/10/07' },
    additions: [] as DrugRecord[], supersedes: [] as SupplementData['categories']['s3']['supersedes'],
  });
  const s3 = cat('54504_with_alternative');
  s3.additions = [{ ...od('dsms-1141284', '2026/10/16', '滅必治軟膠囊50毫克', '新說明'), _來源: 'dsms', _案件編號: '1141284' }];
  s3.supersedes = [{ 品名鍵: normalizeKey('滅必治軟膠囊50毫克'), 公告更新時間: '2026/05/07', 許可證字號: LICENSE, 指紋: normalizeKey('舊說明') }];
  return {
    schema: 1, generated_at: lastSuccessAt, run_id: 'RUN',
    categories: { s3, s4: cat('54505_no_alternative'), s2: cat('54506_resolved') },
  };
}

const iso = (ms: number) => new Date(ms).toISOString();
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;

interface Deferred { promise: Promise<Response>; resolve: (r: Response) => void }
function deferred(): Deferred {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>(r => { resolve = r; });
  return { promise, resolve };
}

function routeFetch(main: Promise<Response>, supp: Promise<Response>) {
  globalThis.fetch = vi.fn((url: RequestInfo | URL) =>
    String(url).includes('supply_supplement') ? supp : main) as typeof fetch;
}

async function flush(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

const amberCount = () => document.querySelector('.stat-chip--amber')?.textContent?.trim();
const redBanner = () => document.querySelector('[data-banner="supplement-warning"]')?.textContent ?? '';
const infoBanner = () => document.querySelector('[data-banner="supplement-info"]')?.textContent ?? '';
const badges = () => [...document.querySelectorAll('a.recovery-tag')].map(a => a.getAttribute('href'));

beforeEach(() => {
  vi.useFakeTimers({ now: NOW });
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('App：補抓套用的實際畫面（B3／B6／B7）', () => {
  it('三類可信 → 舊版隱藏、導覽計數、補抓徽章、琥珀資訊', async () => {
    routeFetch(Promise.resolve(ok(MAIN)), Promise.resolve(ok(supplement(iso(NOW - DAY)))));
    render(<App />);
    await flush();
    expect(amberCount()).toBe('有替代 2');               // 背景藥＋新版滅必治；舊版已隱藏
    expect(infoBanner()).toContain('表中 1 筆較新公告');
    expect(redBanner()).toBe('');
    expect(badges()).toEqual(['https://dsms.fda.gov.tw/DrugList.aspx?s=3']);
  });

  it.each([['補抓檔先到', true], ['主檔先到', false]])('B6 完成順序：%s → 結果相同', async (_n, supplementFirst) => {
    const main = deferred();
    const supp = deferred();
    routeFetch(main.promise, supp.promise);
    render(<App />);
    if (supplementFirst) { supp.resolve(ok(supplement(iso(NOW - DAY)))); await flush(); main.resolve(ok(MAIN)); }
    else { main.resolve(ok(MAIN)); await flush(); supp.resolve(ok(supplement(iso(NOW - DAY)))); }
    await flush();
    expect(amberCount()).toBe('有替代 2');
    expect(infoBanner()).toContain('1 筆舊版公告已依官網隱藏');
  });

  it('B6：補抓檔永遠 pending → 8 秒後主資料照常渲染、紅色警示、不隱藏', async () => {
    routeFetch(Promise.resolve(ok(MAIN)), new Promise<Response>(() => {}));
    render(<App />);
    await flush(7900);
    expect(amberCount()).toBeUndefined();                  // 仍在等補抓（最多 8 秒）
    await flush(200);
    expect(amberCount()).toBe('有替代 2');                 // 只有主檔：舊版與背景藥
    expect(redBanner()).toContain('無法載入公告頁補抓資料（逾時 8 秒）');
    expect(badges()).toEqual([]);
  });
});

describe('App：頁面常駐時隨時間撤銷信任（R4）', () => {
  const loadedFresh = () => supplement(iso(NOW - 2.9 * DAY));   // 0.1 天後到期

  it('不重整：到期計時器觸發 → 轉紅、舊版重新出現', async () => {
    routeFetch(Promise.resolve(ok(MAIN)), Promise.resolve(ok(loadedFresh())));
    render(<App />);
    await flush();
    expect(amberCount()).toBe('有替代 2');
    expect(redBanner()).toBe('');
    await flush(0.1 * DAY + 2000);
    expect(redBanner()).toContain('「有替代」類補抓資料已 3 天未更新');
    expect(redBanner()).toContain('新舊版本並列');
    expect(amberCount()).toBe('有替代 3');                 // 舊版不再隱藏
  });

  it.each([
    ['視窗取得焦點', () => window.dispatchEvent(new Event('focus'))],
    ['切回分頁', () => document.dispatchEvent(new Event('visibilitychange'))],
  ])('時間跳過到期但計時器沒觸發（休眠喚醒）→ %s 立即重算', async (_n, fire) => {
    routeFetch(Promise.resolve(ok(MAIN)), Promise.resolve(ok(loadedFresh())));
    render(<App />);
    await flush();
    expect(amberCount()).toBe('有替代 2');
    vi.setSystemTime(NOW + 4 * DAY);                      // 只動時鐘，不推進計時器
    expect(amberCount()).toBe('有替代 2');
    await act(async () => { fire(); });
    expect(redBanner()).toContain('已 6 天未更新');        // 載入時 2.9 天＋跳過 4 天
    expect(amberCount()).toBe('有替代 3');
  });
});
