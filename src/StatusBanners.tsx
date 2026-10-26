import type { SupplementResult } from './lib/supplement'

// ----------------------------------------------------------------------
// 頁首狀態橫幅：資料過期（CR-06）、上游停更疑似訊號（增量 F）、公告頁補抓（增量 S）。
// 三者各自獨立判斷、可同時出現、互不遮蔽。抽成獨立元件以便測試實際渲染文字（B4）。
// ----------------------------------------------------------------------
export interface StatusBannersProps {
  dataStale: boolean;
  dataAgeDays: number | null;
  upstreamFrozen: boolean;
  frozenRuns?: number;
  upstreamMaxDate?: string | null;
  supplement: SupplementResult | null;
}

const RED_STYLE = {
  background: '#fef2f2',
  borderBottom: '2px solid #fca5a5',
  color: '#991b1b',
  padding: '10px 16px',
  fontSize: '0.875rem',
  fontWeight: 600,
} as const;

const AMBER_STYLE = {
  background: '#fffbeb',
  borderBottom: '2px solid #fcd34d',
  color: '#92400e',
  padding: '10px 16px',
  fontSize: '0.875rem',
  fontWeight: 600,
} as const;

export default function StatusBanners({
  dataStale, dataAgeDays, upstreamFrozen, frozenRuns, upstreamMaxDate, supplement,
}: StatusBannersProps) {
  return (
    <>
      {/* 資料過期警示（CR-06）：逾每週更新週期時醒目提示，避免誤把陳舊資料當現況 */}
      {dataStale && (
        <div role="alert" style={{ ...RED_STYLE, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>⚠️ 資料已超過預定更新週期（每週更新），目前為 {dataAgeDays} 天前。實際供應狀態請以 TFDA 官方公告為準。</span>
        </div>
      )}
      {/* 上游停更疑似訊號（增量 F）：排程照跑但上游公告日期未前進。
          文案刻意不寫「上游已停更」——同日修訂與局部停更不會觸發，這是疑似訊號。 */}
      {upstreamFrozen && (
        <div role="status" style={{ ...AMBER_STYLE, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>
            ⚠️ 已連續 {frozenRuns} 次觀測未見上游公告日期前進
            （最新公告：{upstreamMaxDate}），清單時效需留意。
          </span>
        </div>
      )}
      {/* 公告頁補抓狀態（增量 S）：紅色逐條列出、互不遮蔽 */}
      {supplement && supplement.warnings.length > 0 && (
        <div role="alert" data-banner="supplement-warning" style={RED_STYLE}>
          {supplement.warnings.map(w => <div key={w}>⚠️ {w}</div>)}
          <div>
            🔗 <a href="https://dsms.fda.gov.tw/" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>
              食藥署西藥供應資訊網站
            </a>
          </div>
        </div>
      )}
      {supplement && supplement.info && (
        <div role="status" data-banner="supplement-info" style={AMBER_STYLE}>
          <span>ℹ️ {supplement.info}</span>
        </div>
      )}
    </>
  );
}
