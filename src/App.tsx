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
  
  const [activeTab, setActiveTab] = useState<'list' | 'stats'>('list');
  const [timeMode, setTimeMode] = useState<'month' | 'year'>('month');
  
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterYear, setFilterYear] = useState<string>('all');
  const [filterMonth, setFilterMonth] = useState<string>('all');
  const [showLatestTen, setShowLatestTen] = useState(false);
  const [sortMode, setSortMode] = useState<'newest'|'longest'|'name'>('newest');

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/supply_status_latest.json`)
      .then(res => res.json())
      .then(json => { setData(json); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  // 核心資料管線：精準去重 -> 排序 -> 過濾
  const processedData = useMemo(() => {
    if (!data) return { all: [], availableYears: [], noAlt: [], withAlt: [], resolved: [] };

    const raw106 = (data.datasets['54506_resolved'] || []).map(i => ({ ...i, _theme: 'emerald' as Theme }));
    const raw104 = (data.datasets['54504_with_alternative'] || []).map(i => ({ ...i, _theme: 'amber' as Theme }));
    const raw105 = (data.datasets['54505_no_alternative'] || []).map(i => ({ ...i, _theme: 'red' as Theme }));

    // --- 🚀 修復：時間感知的殭屍紀錄清除邏輯 ---
    // 1. 紀錄每個字號「最新」的解除時間
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

    // 2. 過濾 104/105：如果該字號有「更晚或同日」的解除紀錄，才判定為殭屍並剔除
    const clean104 = raw104.filter(i => {
      const license = (i.許可證字號 || '').trim();
      if (!license) return true; // 無字號無法確認，安全保留
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

    // 3. 重新組合所有真實資料
    let all = [...clean105, ...clean104, ...raw106].map(item => ({
      ...item,
      _days: getDaysDiff(item.公告更新時間),
      _altText: extractAlternative(item.供應狀態)
    }));
    // --------------------------------------------

    const availableYears = Array.from(new Set(all.map(i => (i.公告更新時間||'').split('/')[0]))).filter(Boolean).sort().reverse();

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
        const matchSearch = (i.中文品名 || '').toLowerCase().includes(searchTerm.toLowerCase()) || (i.許可證字號 || '').includes(searchTerm);
        const matchStatus = filterStatus === 'all' ? true : i._theme === filterStatus;
        const matchYear = filterYear === 'all' ? true : parts[0] === filterYear;
        const matchMonth = filterMonth === 'all' ? true : parts[1]?.padStart(2, '0') === filterMonth;
        return matchSearch && matchStatus && matchYear && matchMonth;
      });
    }

    return { 
      all, availableYears,
      noAlt: all.filter(i => i._theme === 'red'),
      withAlt: all.filter(i => i._theme === 'amber'),
      resolved: all.filter(i => i._theme === 'emerald')
    };
  }, [data, searchTerm, filterStatus, filterYear, filterMonth, showLatestTen, sortMode]);

  const stats = useCompositeStats(processedData.all);
  const chartData = timeMode === 'month' ? stats.monthlyChart : stats.yearlyChart;

  if (loading) return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f0f4f8', gap: '16px' }}>
      <div style={{ width: '48px', height: '48px', border: '4px solid #e2e8f0', borderTop: '4px solid #2563eb', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
      <p style={{ color: '#64748b', fontWeight: 600 }}>系統讀取中…</p>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', display: 'flex', flexDirection: 'column', fontFamily: '"Noto Sans TC", sans-serif' }}>
      <PwaBanners />
      {/* 導覽列 */}
      <nav style={{ backgroundColor: '#0f172a', padding: '16px 24px', position: 'sticky', top: 0, zIndex: 50, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
        <div style={{ maxWidth: '1152px', margin: '0 auto', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '20px', color: 'white' }}>⚕</div>
            <div>
              <div style={{ color: '#f8fafc', fontWeight: 700, fontSize: '18px', lineHeight: 1.2 }}>西藥供應資訊儀表板</div>
              <div style={{ color: '#94a3b8', fontSize: '12px' }}>NHI Drug Supply Monitor</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '8px 16px', width: '100%', maxWidth: '350px' }}>
            <span style={{ color: '#475569', fontSize: '16px', marginRight: '8px' }}>🔍</span>
            <input type="text" placeholder="搜尋藥品..." onChange={e => setSearchTerm(e.target.value)} style={{ border: 'none', outline: 'none', flex: 1, fontSize: '15px', color: '#e2e8f0', background: 'transparent' }} />
          </div>
        </div>
      </nav>

      {/* 主內容區 */}
      <main style={{ maxWidth: '1152px', margin: '24px auto 0', padding: '0 16px', flex: 1, width: '100%', boxSizing: 'border-box' }}>
        
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
  const p = { red: '#ef4444', amber: '#f59e0b', emerald: '#10b981' }[colorTheme as Theme];
  return (
    <section style={{ backgroundColor: '#ffffff', borderRadius: '16px', border: `1px solid ${p}40`, overflow: 'hidden', marginBottom: '16px' }}>
      <div style={{ backgroundColor: `${p}10`, borderBottom: `1px solid ${p}40`, padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ width: '4px', height: '24px', backgroundColor: p, borderRadius: '2px' }} />
        <h2 style={{ fontSize: '16px', fontWeight: 700, flex: 1, margin: 0, color: '#1e293b' }}>{title}</h2>
        <span style={{ backgroundColor: p, color: '#fff', fontSize: '12px', fontWeight: 700, padding: '3px 10px', borderRadius: '99px' }}>{list.length} 筆</span>
      </div>
      <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {list.map((item: any, i: number) => <DrugCard key={i} item={item} theme={colorTheme} />)}
      </div>
    </section>
  );
}

function DrugCard({ item, theme }: any) {
  const [open, setOpen] = useState(false);
  const rec = extractRecoveryTime(item.供應狀態);
  const t = { red: {bg:'#fee2e2', text:'#991b1b'}, amber: {bg:'#fef3c7', text:'#92400e'}, emerald: {bg:'#d1fae5', text:'#065f46'} }[theme as Theme];
  
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: '12px', backgroundColor: '#fff', transition: 'box-shadow 0.2s', boxShadow: open ? '0 4px 12px rgba(0,0,0,0.08)' : '0 1px 2px rgba(0,0,0,0.02)' }}>
      <div onClick={() => setOpen(!open)} style={{ padding: '16px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', backgroundColor: '#f1f5f9', padding: '2px 8px', borderRadius: '6px' }}>{item.公告更新時間}</span>
            {theme !== 'emerald' && <span style={{ fontSize: '12px', fontWeight: 700, color: '#dc2626', backgroundColor: '#fee2e2', padding: '2px 8px', borderRadius: '6px' }}>🔥 缺藥 {item._days} 天</span>}
          </div>
          <span style={{ color: '#94a3b8', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>▾</span>
        </div>
        
        <div style={{ fontWeight: 700, fontSize: '15px', color: '#1e293b' }}>{item.中文品名}</div>
        <div style={{ fontSize: '13px', color: '#94a3b8', fontFamily: 'monospace' }}>{item.許可證字號}</div>
        
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '4px' }}>
           {item._altText && theme !== 'emerald' && <span style={{ fontSize: '12px', fontWeight: 600, color: '#0369a1', backgroundColor: '#e0f2fe', padding: '4px 8px', borderRadius: '6px' }}>💡 替代：{item._altText}</span>}
           {rec && <span style={{ fontSize: '12px', fontWeight: 600, color: t.text, backgroundColor: t.bg, padding: '4px 8px', borderRadius: '6px' }}>⏳ {rec}</span>}
        </div>
      </div>
      
      {open && (
        <div style={{ padding: '16px', backgroundColor: '#f8fafc', borderTop: '1px dashed #cbd5e1', fontSize: '14px', whiteSpace: 'pre-line', color: '#334155', lineHeight: 1.6 }}>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px', fontWeight: 700 }}>📄 官方供應狀態說明</div>
          {item.供應狀態?.replace(/\\r\\n/g, '\n')}
        </div>
      )}
    </div>
  );
}