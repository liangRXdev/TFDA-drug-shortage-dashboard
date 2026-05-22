import { useEffect, useState, useMemo } from 'react'
import PwaBanners from './PwaBanners'
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, 
  Tooltip, Legend, ResponsiveContainer 
} from 'recharts';
import './index.css'

// ----------------------------------------------------------------------
// 型別定義
// ----------------------------------------------------------------------
interface DrugRecord {
  編號: string;
  中文品名: string;
  許可證字號: string;
  供應狀態: string;
  公告更新時間: string;
  _theme?: Theme;
  _days?: number;
  _altText?: string | null;
}

interface SupplyData {
  last_updated: string;
  datasets: { [key: string]: DrugRecord[] };
}

type Theme = 'red' | 'amber' | 'emerald';

// ----------------------------------------------------------------------
// 工具函數
// ----------------------------------------------------------------------
const getDaysDiff = (dateStr: string) => {
  if (!dateStr) return 0;
  const parts = dateStr.split('/');
  if (parts.length < 2) return 0;
  const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2] || 1));
  return Math.max(0, Math.floor((new Date().getTime() - d.getTime()) / (1000 * 60 * 60 * 24)));
};

const extractAlternative = (text: string) => {
  if (!text) return null;
  const match = text.match(/(?:建議替代|替代藥品|替代品項|改用|可由)[：:\s]*([^。，\n;；]+)/);
  return match ? match[1].trim() : null;
};

const extractRecoveryTime = (text: string) => {
  if (!text) return null;
  const match = text.replace(/\\r\\n/g, '').match(/(無法預計[^\u3002，,]*|預計[^\u3002，]*(恢復|供應)[^\u3002，]*)/);
  return match ? match[0] : null;
};

function groupByYearMonth(list: DrugRecord[]) {
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
// 統計 Hook
// ----------------------------------------------------------------------
const useCompositeStats = (allData: DrugRecord[]) => {
  return useMemo(() => {
    if (!allData.length) return { uniqueDrugCount: 0, monthlyChart: [], yearlyChart: [] };
    
    // 修正：若無字號，改用品名作為唯一值辨識，避免空字號藥品互相覆蓋
    const uniqueDrugs = new Set(allData.map(item => (item.許可證字號 || item.中文品名 || '未知').trim()));
    
    const monthlyMap: Record<string, any> = {};
    const yearlyMap: Record<string, any> = {};

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

    const format = (map: Record<string, any>) => 
      Object.values(map).sort((a: any, b: any) => a.label.localeCompare(b.label)).map(d => ({
        name: d.label, '無替代(紅)': d.red, '有替代(黃)': d.amber, '已解除(綠)': d.emerald
      }));

    return { uniqueDrugCount: uniqueDrugs.size, monthlyChart: format(monthlyMap), yearlyChart: format(yearlyMap) };
  }, [allData]);
};

// ----------------------------------------------------------------------
// 主元件
// ----------------------------------------------------------------------
export default function App() {
  const [data, setData] = useState<SupplyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  const [activeTab, setActiveTab] = useState<'list' | 'stats'>('list');
  const [timeMode, setTimeMode] = useState<'month' | 'year'>('month');
  
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterYear, setFilterYear] = useState<string>('all');
  const [filterMonth, setFilterMonth] = useState<string>('all');
  const [showLatestTen, setShowLatestTen] = useState(false);
  const [sortMode, setSortMode] = useState<'newest'|'longest'|'name'>('newest');

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(t);
  }, [searchTerm]);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/supply_status_latest.json`)
      .then(res => res.json())
      .then(json => { setData(json); setLoading(false); })
      .catch(() => { setLoading(false); setFetchError(true); });
  }, []);

  // 核心資料管線 Step 1：殭屍清除 + meta 掛載（不含篩選）
  const cleanedData = useMemo(() => {
    if (!data) return { all: [], availableYears: [], noAlt: 0, withAlt: 0, resolved: 0 };

    const raw106 = (data.datasets['54506_resolved'] || []).map(i => ({ ...i, _theme: 'emerald' as Theme }));
    const raw104 = (data.datasets['54504_with_alternative'] || []).map(i => ({ ...i, _theme: 'amber' as Theme }));
    const raw105 = (data.datasets['54505_no_alternative'] || []).map(i => ({ ...i, _theme: 'red' as Theme }));

    const resolvedDates = new Map<string, number>();
    raw106.forEach(i => {
      const license = (i.許可證字號 || '').trim();
      if (license) {
        const dTime = new Date(i.公告更新時間).getTime();
        if (!resolvedDates.has(license) || dTime > resolvedDates.get(license)!) {
          resolvedDates.set(license, dTime);
        }
      }
    });

    const clean104 = raw104.filter(i => {
      const license = (i.許可證字號 || '').trim();
      if (!license) return true;
      const resTime = resolvedDates.get(license);
      const myTime = new Date(i.公告更新時間).getTime();
      return !(resTime && resTime >= myTime);
    });

    const clean105 = raw105.filter(i => {
      const license = (i.許可證字號 || '').trim();
      if (!license) return true;
      const resTime = resolvedDates.get(license);
      const myTime = new Date(i.公告更新時間).getTime();
      return !(resTime && resTime >= myTime);
    });

    const all = [...clean105, ...clean104, ...raw106]
      .filter(i => (i.中文品名 || '').trim() || (i.許可證字號 || '').trim())
      .map(item => ({
        ...item,
        _days: getDaysDiff(item.公告更新時間),
        _altText: extractAlternative(item.供應狀態)
      }));

    const availableYears = Array.from(new Set(all.map(i => (i.公告更新時間||'').split('/')[0]))).filter(Boolean).sort().reverse();

    return {
      all,
      availableYears,
      noAlt: all.filter(i => i._theme === 'red').length,
      withAlt: all.filter(i => i._theme === 'amber').length,
      resolved: all.filter(i => i._theme === 'emerald').length,
    };
  }, [data]);

  // 核心資料管線 Step 2：排序 + 篩選
  const processedData = useMemo(() => {
    let all = [...cleanedData.all];

    all.sort((a, b) => {
      if (sortMode === 'newest') return new Date(b.公告更新時間).getTime() - new Date(a.公告更新時間).getTime();
      if (sortMode === 'longest') return (b._days || 0) - (a._days || 0);
      if (sortMode === 'name') return (a.中文品名 || '').localeCompare(b.中文品名 || '');
      return 0;
    });

    if (showLatestTen) {
      all = all.slice(0, 10);
    } else {
      all = all.filter(i => {
        const parts = (i.公告更新時間 || '').split('/');
        const matchSearch = (i.中文品名 || '').toLowerCase().includes(debouncedSearch.toLowerCase()) || (i.許可證字號 || '').includes(debouncedSearch);
        const matchStatus = filterStatus === 'all' ? true : i._theme === filterStatus;
        const matchYear = filterYear === 'all' ? true : parts[0] === filterYear;
        const matchMonth = filterMonth === 'all' ? true : parts[1]?.padStart(2, '0') === filterMonth;
        return matchSearch && matchStatus && matchYear && matchMonth;
      });
    }

    return {
      all,
      availableYears: cleanedData.availableYears,
      noAlt: all.filter(i => i._theme === 'red'),
      withAlt: all.filter(i => i._theme === 'amber'),
      resolved: all.filter(i => i._theme === 'emerald'),
    };
  }, [cleanedData, debouncedSearch, filterStatus, filterYear, filterMonth, showLatestTen, sortMode]);

  const stats = useCompositeStats(processedData.all);
  const chartData = timeMode === 'month' ? stats.monthlyChart : stats.yearlyChart;

  if (loading) return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f0f4f8', gap: '16px' }}>
      <div style={{ width: '48px', height: '48px', border: '4px solid #e2e8f0', borderTop: '4px solid #2563eb', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
      <p style={{ color: '#64748b', fontWeight: 600 }}>系統讀取中…</p>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  if (fetchError) return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f0f4f8', gap: '12px', padding: '24px' }}>
      <div style={{ fontSize: '48px' }}>📡</div>
      <p style={{ color: '#0f172a', fontWeight: 700, fontSize: '18px', margin: 0 }}>無法載入供應資料</p>
      <p style={{ color: '#64748b', fontSize: '14px', margin: 0, textAlign: 'center' }}>
        請確認網路連線後重新整理頁面。<br />若先前已造訪過本站，快取資料應可自動還原。
      </p>
      <button
        onClick={() => window.location.reload()}
        style={{ background: '#0891b2', color: '#fff', border: 'none', borderRadius: '8px', padding: '8px 20px', cursor: 'pointer', fontWeight: 600, fontSize: '14px' }}
      >
        重新整理
      </button>
    </div>
  );

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', display: 'flex', flexDirection: 'column', fontFamily: '"Noto Sans TC", sans-serif' }}>
      <PwaBanners />
      {/* 導覽列 */}
      <nav className="nav">
        <div className="nav__inner">
          <div className="nav__brand">
            <div className="nav__icon">⚕</div>
            <div>
              <div className="nav__title">西藥供應資訊儀表板</div>
              <div className="nav__subtitle">NHI Drug Supply Monitor</div>
              {data?.last_updated && (
                <div className="nav__meta">資料更新：{data.last_updated.slice(0, 16).replace('T', ' ')}</div>
              )}
            </div>
          </div>
          <div className="nav__stats">
            <div className="stat-chip stat-chip--red">
              <span className="stat-chip__dot" />
              無替代 {cleanedData.noAlt}
            </div>
            <div className="stat-chip stat-chip--amber">
              <span className="stat-chip__dot" />
              有替代 {cleanedData.withAlt}
            </div>
            <div className="stat-chip stat-chip--emerald">
              <span className="stat-chip__dot" />
              已解除 {cleanedData.resolved}
            </div>
          </div>
          <div className="search-wrap">
            <span className="search-wrap__icon">🔍</span>
            <input
              type="text"
              className="search-input"
              placeholder="搜尋藥品..."
              onChange={e => setSearchTerm(e.target.value)}
            />
          </div>
        </div>
      </nav>

      {/* 主內容區 */}
      <main className="main" style={{ flex: 1 }}>
        
        {/* 分頁切換 */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', backgroundColor: '#e2e8f0', padding: '4px', borderRadius: '12px', width: 'fit-content' }}>
          <button onClick={() => setActiveTab('list')} style={{ padding: '8px 20px', borderRadius: '8px', fontWeight: 700, fontSize: '14px', cursor: 'pointer', border: 'none', backgroundColor: activeTab === 'list' ? '#ffffff' : 'transparent', color: activeTab === 'list' ? '#1d4ed8' : '#64748b', boxShadow: activeTab === 'list' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none' }}>📋 清單列表</button>
          <button onClick={() => setActiveTab('stats')} style={{ padding: '8px 20px', borderRadius: '8px', fontWeight: 700, fontSize: '14px', cursor: 'pointer', border: 'none', backgroundColor: activeTab === 'stats' ? '#ffffff' : 'transparent', color: activeTab === 'stats' ? '#1d4ed8' : '#64748b', boxShadow: activeTab === 'stats' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none' }}>📊 數據分析</button>
        </div>

        {activeTab === 'list' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            
            {/* 篩選與排序控制台 */}
            <div style={{ backgroundColor: '#ffffff', padding: '16px', borderRadius: '12px', border: '1px solid #e2e8f0', display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' }}>
              <select value={filterStatus} disabled={showLatestTen} onChange={e => setFilterStatus(e.target.value)} style={{ padding: '8px', borderRadius: '8px', border: '1px solid #cbd5e1', outline: 'none', cursor: 'pointer' }}>
                <option value="all">狀態：全部 ({processedData.all.length})</option>
                <option value="red">無替代 ({processedData.noAlt.length})</option>
                <option value="amber">有替代 ({processedData.withAlt.length})</option>
                <option value="emerald">已解除 ({processedData.resolved.length})</option>
              </select>
              <select value={filterYear} disabled={showLatestTen} onChange={e => setFilterYear(e.target.value)} style={{ padding: '8px', borderRadius: '8px', border: '1px solid #cbd5e1', outline: 'none', cursor: 'pointer' }}>
                <option value="all">年份：全部</option>
                {processedData.availableYears.map(y => <option key={y} value={y}>{y}年</option>)}
              </select>
              <select value={filterMonth} disabled={showLatestTen} onChange={e => setFilterMonth(e.target.value)} style={{ padding: '8px', borderRadius: '8px', border: '1px solid #cbd5e1', outline: 'none', cursor: 'pointer' }}>
                <option value="all">月份：全部</option>
                {Array.from({ length: 12 }, (_, i) => (i + 1).toString().padStart(2, '0')).map(m => <option key={m} value={m}>{m}月</option>)}
              </select>
              <select value={sortMode} onChange={e => setSortMode(e.target.value as any)} style={{ padding: '8px', borderRadius: '8px', border: '1px solid #cbd5e1', outline: 'none', cursor: 'pointer' }}>
                <option value="newest">排序：最新公告</option>
                <option value="longest">排序：缺藥最久</option>
                <option value="name">排序：名稱 A-Z</option>
              </select>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px', fontWeight: 700, color: '#2563eb', cursor: 'pointer', borderLeft: '1px solid #e2e8f0', paddingLeft: '16px' }}>
                <input type="checkbox" checked={showLatestTen} onChange={e => setShowLatestTen(e.target.checked)} style={{ transform: 'scale(1.2)' }} /> 顯示最新十筆
              </label>
            </div>

            {/* 清單渲染 */}
            {(filterStatus === 'all' || filterStatus === 'red') && <Section title="經評估【無】替代藥品" colorTheme="red" list={processedData.noAlt} />}
            {(filterStatus === 'all' || filterStatus === 'amber') && <Section title="經評估【有】替代藥品" colorTheme="amber" list={processedData.withAlt} />}
            {(filterStatus === 'all' || filterStatus === 'emerald') && <Section title="藥品已解除短缺" colorTheme="emerald" list={processedData.resolved} />}
            
            {processedData.all.length === 0 && (
              <div style={{ textAlign: 'center', padding: '64px', color: '#94a3b8', backgroundColor: '#fff', borderRadius: '16px', border: '1px dashed #cbd5e1' }}>
                找不到符合篩選條件的藥品
              </div>
            )}
          </div>
        ) : (
          /* 數據分析圖表 */
          <div style={{ backgroundColor: '#ffffff', padding: '24px', borderRadius: '16px', border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 700 }}>📊 供應趨勢統計</h2>
              <div style={{ display: 'flex', backgroundColor: '#f1f5f9', padding: '4px', borderRadius: '8px' }}>
                <button onClick={() => setTimeMode('month')} style={{ padding: '6px 16px', borderRadius: '6px', fontWeight: 700, fontSize: '13px', border: 'none', backgroundColor: timeMode === 'month' ? '#ffffff' : 'transparent', color: timeMode === 'month' ? '#2563eb' : '#64748b' }}>月統計</button>
                <button onClick={() => setTimeMode('year')} style={{ padding: '6px 16px', borderRadius: '6px', fontWeight: 700, fontSize: '13px', border: 'none', backgroundColor: timeMode === 'year' ? '#ffffff' : 'transparent', color: timeMode === 'year' ? '#2563eb' : '#64748b' }}>年統計</button>
              </div>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
               <div style={{ backgroundColor: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '12px', padding: '16px' }}>
                 <div style={{ fontSize: '13px', fontWeight: 700, color: '#3b82f6', marginBottom: '8px' }}>受影響藥品項數</div>
                 <div style={{ fontSize: '28px', fontWeight: 900, color: '#1e40af' }}>{stats.uniqueDrugCount} <span style={{ fontSize: '14px', fontWeight: 500 }}>項</span></div>
               </div>
               <div style={{ backgroundColor: '#fffbeb', border: '1px solid #fde68a', borderRadius: '12px', padding: '16px' }}>
                 <div style={{ fontSize: '13px', fontWeight: 700, color: '#d97706', marginBottom: '8px' }}>累計通報件數</div>
                 <div style={{ fontSize: '28px', fontWeight: 900, color: '#b45309' }}>{processedData.noAlt.length + processedData.withAlt.length} <span style={{ fontSize: '14px', fontWeight: 500 }}>件</span></div>
               </div>
               <div style={{ backgroundColor: '#f0fdf4', border: '1px solid #a7f3d0', borderRadius: '12px', padding: '16px' }}>
                 <div style={{ fontSize: '13px', fontWeight: 700, color: '#059669', marginBottom: '8px' }}>已解除短缺件數</div>
                 <div style={{ fontSize: '28px', fontWeight: 900, color: '#065f46' }}>{processedData.resolved.length} <span style={{ fontSize: '14px', fontWeight: 500 }}>件</span></div>
               </div>
            </div>

            <div style={{ height: '400px', width: '100%', overflowX: 'auto' }}>
              <div style={{ minWidth: '500px', height: '100%' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 20, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="name" tick={{fontSize: 12}} axisLine={{stroke: '#cbd5e1'}} tickLine={false} />
                    <YAxis tick={{fontSize: 12}} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{fill: '#f8fafc'}} contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'}} />
                    <Legend wrapperStyle={{paddingTop: '20px'}} iconType="circle" />
                    <Bar dataKey="無替代(紅)" stackId="a" fill="#ef4444" radius={[0, 0, 0, 0]} barSize={35} />
                    <Bar dataKey="有替代(黃)" stackId="a" fill="#f59e0b" radius={[4, 4, 0, 0]} barSize={35} />
                    <Bar dataKey="已解除(綠)" fill="#10b981" radius={[4, 4, 0, 0]} barSize={35} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* 底部警語與資訊區 */}
      <footer style={{ backgroundColor: '#0f172a', color: '#94a3b8', padding: '32px 16px', marginTop: '64px' }}>
        <div style={{ maxWidth: '1152px', margin: '0 auto', textAlign: 'center' }}>
          <p style={{ fontSize: '14px', marginBottom: '12px', lineHeight: 1.6 }}>
            [ 依政府 OpenData API 抓取最新資訊，但最新訊息仍建議查閱 TFDA 網頁 ]
          </p>
          <a 
            href="https://dsms.fda.gov.tw/" 
            target="_blank" 
            rel="noopener noreferrer"
            style={{ color: '#60a5fa', fontSize: '14px', textDecoration: 'none', fontWeight: 600 }}
          >
            🔗 西藥醫療器材供應平台 (官方網站)
          </a>
          <div style={{ marginTop: '20px', fontSize: '12px', opacity: 0.6 }}>
            &copy; 2026 Clinical Pharmacy Supply Dashboard
          </div>
        </div>
      </footer>
    </div>
  );
}

// ----------------------------------------------------------------------
// 子元件區
// ----------------------------------------------------------------------
function Section({ title, colorTheme, list }: any) {
  if (!list.length) return null;
  const grouped = groupByYearMonth(list);
  return (
    <section className={`section section--${colorTheme}`}>
      <div className="section__header">
        <div className="section__bar" />
        <h2 className="section__title">{title}</h2>
        <div className="section__divider" />
        <span className="section__count">{list.length} 筆</span>
      </div>
      <div className="section__body">
        {grouped.map(({ year, months }, yi) => (
          <YearGroup key={year} year={year} months={months} theme={colorTheme} defaultOpen={yi === 0} />
        ))}
      </div>
    </section>
  );
}

function YearGroup({ year, months, theme, defaultOpen }: { year: string, months: { month: string, items: DrugRecord[] }[], theme: Theme, defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const total = months.reduce((s, m) => s + m.items.length, 0);
  return (
    <div className="year-group">
      <button className="year-group__toggle" onClick={() => setOpen(!open)}>
        <span className="year-group__label">{year} 年</span>
        <div className="year-group__meta">
          <span>{total} 筆</span>
          <span className={`year-group__chevron${open ? ' year-group__chevron--open' : ''}`}>▼</span>
        </div>
      </button>
      {open && (
        <div className="year-group__content">
          {months.map(({ month, items }, mi) => (
            <MonthGroup key={month} month={month} items={items} theme={theme} defaultOpen={mi === 0} />
          ))}
        </div>
      )}
    </div>
  );
}

function MonthGroup({ month, items, theme, defaultOpen }: { month: string, items: DrugRecord[], theme: Theme, defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="month-group">
      <button className="month-group__toggle" onClick={() => setOpen(!open)}>
        <span className="month-group__label">{month}月 · {items.length} 筆</span>
        <span className={`month-group__chevron${open ? ' month-group__chevron--open' : ''}`}>▼</span>
      </button>
      {open && (
        <div className="month-group__list">
          {items.map((item, i) => (
            <DrugCard key={item.許可證字號 || item.編號 || String(i)} item={item} theme={theme} />
          ))}
        </div>
      )}
    </div>
  );
}

function DrugCard({ item, theme }: { item: DrugRecord, theme: Theme }) {
  const [open, setOpen] = useState(false);
  const rec = extractRecoveryTime(item.供應狀態);
  const [zhName, enName] = (item.中文品名 || '').split('\n');
  const d = item._days ?? 0;

  return (
    <div className="drug-card">
      <div
        className={`drug-card__row${open ? ' drug-card__row--expanded' : ''}`}
        onClick={() => setOpen(!open)}
      >
        <div className="drug-card__info">
          <div className="drug-card__name">{zhName}</div>
          {enName && <div className="drug-card__code">{enName}</div>}
          <div className="drug-card__code">{item.許可證字號}</div>
          <div className="drug-card__date">{item.公告更新時間}</div>
        </div>
        <div className="drug-card__right">
          {theme !== 'emerald' && (
            <span className={`recovery-tag recovery-tag--${d > 30 ? 'red' : d >= 14 ? 'amber' : 'default'}`}>
              缺藥 {d} 天
            </span>
          )}
          {item._altText && theme !== 'emerald' && (
            <span className="recovery-tag recovery-tag--amber" style={{ maxWidth: '140px' }}>
              💡 {item._altText}
            </span>
          )}
          {rec && (
            <span className={`recovery-tag recovery-tag--${theme === 'emerald' ? 'emerald' : theme}`} style={{ maxWidth: '160px' }}>
              ⏳ {rec}
            </span>
          )}
          <span className={`drug-card__chevron${open ? ' drug-card__chevron--open' : ''}`}>▼</span>
        </div>
      </div>
      {open && (
        <div className="drug-detail">
          <div className="drug-detail__inner">
            <div className="drug-detail__titlebar">
              <div className={`drug-detail__dot drug-detail__dot--${theme === 'emerald' ? 'green' : theme}`} />
              <span className="drug-detail__label">官方供應狀態說明</span>
            </div>
            <div className="drug-detail__body">
              {item.供應狀態?.replace(/\\r\\n/g, '\n')}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}