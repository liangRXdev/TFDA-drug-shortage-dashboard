import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import StatusBanners, { type StatusBannersProps } from './StatusBanners';
import type { SupplementResult } from './lib/supplement';
import type { SupplyData } from './lib/dataPipeline';

// ----------------------------------------------------------------------
// B4（T5）：驗證實際渲染出的文字，而不只是 applySupplement 回傳的字串。
// 以既有的 react-dom/server 靜態渲染，不另外引入 DOM 測試依賴。
// ----------------------------------------------------------------------
const EMPTY_DATA: SupplyData = { last_updated: '2026-10-23 04:53:03', datasets: {} };

function result(o: Partial<SupplementResult>): SupplementResult {
  return { data: EMPTY_DATA, warnings: [], info: null, trusted: true, added: 0, hidden: 0, ...o };
}

function render(o: Partial<StatusBannersProps>): string {
  const props: StatusBannersProps = {
    dataStale: false, dataAgeDays: null, upstreamFrozen: false, supplement: null, ...o,
  };
  return renderToStaticMarkup(<StatusBanners {...props} />);
}

const text = (html: string) => html.replace(/<[^>]+>/g, '');

describe('StatusBanners：實際渲染', () => {
  it('多條補抓紅色警示全部渲染，並附官網連結', () => {
    const html = render({ supplement: result({ trusted: false, warnings: ['甲類失敗。', '乙類過期。', '新舊版本並列。'] }) });
    expect(html).toContain('data-banner="supplement-warning"');
    for (const w of ['甲類失敗。', '乙類過期。', '新舊版本並列。']) expect(text(html)).toContain(`⚠️ ${w}`);
    expect(html).toContain('href="https://dsms.fda.gov.tw/"');
    expect(html).not.toContain('data-banner="supplement-info"');
  });

  it('可信且有差異 → 只有琥珀資訊，沒有紅色', () => {
    const html = render({ supplement: result({ info: '表中 3 筆較新公告…' }) });
    expect(text(html)).toContain('ℹ️ 表中 3 筆較新公告…');
    expect(html).not.toContain('role="alert"');
  });

  it('可信且無差異 → 不渲染任何補抓橫幅', () => {
    expect(render({ supplement: result({}) })).toBe('');
  });

  it('與 CR-06 過期、增量 F 停更橫幅同時出現，互不遮蔽', () => {
    const html = render({
      dataStale: true, dataAgeDays: 12,
      upstreamFrozen: true, frozenRuns: 4, upstreamMaxDate: '2026/10/07',
      supplement: result({ trusted: false, warnings: ['「已恢復」類補抓失敗。'] }),
    });
    const t = text(html);
    expect(t).toContain('目前為 12 天前');
    expect(t).toContain('已連續 4 次觀測未見上游公告日期前進');
    expect(t).toContain('「已恢復」類補抓失敗。');
    expect(html.match(/role="alert"/g)).toHaveLength(2);
  });

  it('補抓結果尚未就緒（null）時不渲染補抓橫幅', () => {
    expect(render({ supplement: null })).toBe('');
  });
});
