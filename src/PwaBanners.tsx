import { useEffect, useRef, useState } from 'react'
import { useRegisterSW } from 'virtual:pwa-register/react'

export default function PwaBanners() {
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW()

  const [isOffline, setIsOffline] = useState(!navigator.onLine)
  const [showInstall, setShowInstall] = useState(false)
  const deferredPrompt = useRef<Event & { prompt: () => void } | null>(null)

  useEffect(() => {
    const goOffline = () => setIsOffline(true)
    const goOnline = () => setIsOffline(false)
    window.addEventListener('offline', goOffline)
    window.addEventListener('online', goOnline)
    return () => {
      window.removeEventListener('offline', goOffline)
      window.removeEventListener('online', goOnline)
    }
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault()
      deferredPrompt.current = e as Event & { prompt: () => void }
      setShowInstall(true)
    }
    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const handleInstall = () => {
    deferredPrompt.current?.prompt()
    setShowInstall(false)
  }

  return (
    <>
      {isOffline && (
        <div style={{
          background: '#fef3c7',
          borderBottom: '2px solid #fcd34d',
          color: '#92400e',
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '0.875rem',
          fontWeight: 500,
        }}>
          <span>⚠️ 目前離線，顯示本機快取資料（每週更新）</span>
        </div>
      )}

      {needRefresh && (
        <div style={{
          background: '#eff6ff',
          borderBottom: '2px solid #93c5fd',
          color: '#1e40af',
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: '0.875rem',
          fontWeight: 500,
        }}>
          <span>🔄 資料已更新，點擊重新載入</span>
          <button
            onClick={() => updateServiceWorker(true)}
            style={{
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              padding: '4px 12px',
              cursor: 'pointer',
              fontSize: '0.8rem',
            }}
          >
            重新載入
          </button>
        </div>
      )}

      {showInstall && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          zIndex: 9999,
          background: '#ffffff',
          border: '1px solid #a5f3fc',
          borderLeft: '4px solid #0891b2',
          borderRadius: '12px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
          color: '#164e63',
          maxWidth: '320px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '10px',
          fontSize: '0.84rem',
        }}>
          <span style={{ flex: 1 }}>📲 加入主畫面，隨時查看藥品短缺資訊</span>
          <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
            <button
              onClick={handleInstall}
              style={{
                background: '#0891b2',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                padding: '4px 10px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                whiteSpace: 'nowrap',
              }}
            >
              安裝
            </button>
            <button
              onClick={() => setShowInstall(false)}
              style={{
                background: 'transparent',
                color: '#64748b',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                padding: '4px 8px',
                cursor: 'pointer',
                fontSize: '0.8rem',
              }}
            >
              ✕
            </button>
          </div>
        </div>
      )}
    </>
  )
}
