import { useState } from 'react'
import { AuthProvider, useAuth } from './AuthContext'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Chart from './pages/Chart'
import Analytics from './pages/Analytics'

type Page = 'dashboard' | 'chart' | 'analytics' | 'settings'

const NAV_ITEMS: { page: Page; label: string; icon: string }[] = [
  { page: 'dashboard', label: '仪表盘', icon: '⚡' },
  { page: 'chart',     label: '价格',   icon: '📈' },
  { page: 'analytics', label: '收益',   icon: '💰' },
  { page: 'settings',  label: '设置',   icon: '⚙️' },
]

function TopBar({ logout }: { logout: () => void }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 bg-gray-900/95 backdrop-blur-sm border-b border-gray-800 sticky top-0 z-10">
      <div className="flex items-center gap-2">
        <span className="text-lg leading-none">⚡</span>
        <span className="text-white font-semibold text-sm">Fox-Amber</span>
        <span className="text-gray-600 text-xs hidden sm:inline">套利系统</span>
      </div>
      <button
        onClick={logout}
        className="text-gray-500 hover:text-gray-300 text-xs transition-colors px-2 py-1 rounded-lg hover:bg-gray-800"
      >
        退出
      </button>
    </div>
  )
}

function BottomNav({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  return (
    <div className="fixed bottom-0 left-0 right-0 bg-gray-900/95 backdrop-blur-sm border-t border-gray-800 z-10">
      <div className="flex max-w-2xl mx-auto">
        {NAV_ITEMS.map(({ page: p, label, icon }) => (
          <button
            key={p}
            onClick={() => setPage(p)}
            className={`flex-1 flex flex-col items-center justify-center py-3 gap-0.5 transition-all ${
              page === p ? 'text-blue-400' : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            <span className={`text-xl leading-none transition-transform duration-150 ${page === p ? 'scale-110' : 'scale-100'}`}>
              {icon}
            </span>
            <span className={`text-xs font-medium ${page === p ? 'text-blue-400' : 'text-gray-500'}`}>
              {label}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function App() {
  const { token, logout } = useAuth()
  const [page, setPage] = useState<Page>('dashboard')

  if (!token) return <Login />

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <TopBar logout={logout} />
      <main className="max-w-2xl mx-auto p-4 pb-24">
        {page === 'dashboard' && <Dashboard />}
        {page === 'chart'     && <Chart />}
        {page === 'analytics' && <Analytics />}
        {page === 'settings'  && <Settings />}
      </main>
      <BottomNav page={page} setPage={setPage} />
    </div>
  )
}

export default function Root() {
  return (
    <AuthProvider>
      <App />
    </AuthProvider>
  )
}
