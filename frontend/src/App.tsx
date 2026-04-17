import { useState } from 'react'
import { AuthProvider, useAuth } from './AuthContext'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Chart from './pages/Chart'
import Analytics from './pages/Analytics'

type Page = 'dashboard' | 'chart' | 'analytics' | 'settings'

function Nav({ page, setPage, logout }: { page: Page; setPage: (p: Page) => void; logout: () => void }) {
  const btn = (p: Page, label: string) => (
    <button
      onClick={() => setPage(p)}
      className={`px-4 py-2 text-sm rounded-lg transition-colors ${
        page === p ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
      }`}
    >
      {label}
    </button>
  )
  return (
    <div className="flex items-center gap-1 px-4 py-3 bg-gray-900 border-b border-gray-800 sticky top-0 z-10">
      <span className="text-white font-semibold mr-3 text-sm">⚡ Fox-Amber</span>
      {btn('dashboard', '仪表盘')}
      {btn('chart', '价格图表')}
      {btn('analytics', '收益分析')}
      {btn('settings', '参数设置')}
      <button onClick={logout} className="ml-auto text-gray-500 hover:text-white text-sm transition-colors">
        退出
      </button>
    </div>
  )
}

function App() {
  const { token, logout } = useAuth()
  const [page, setPage] = useState<Page>('dashboard')

  if (!token) return <Login />

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <Nav page={page} setPage={setPage} logout={logout} />
      <main className="max-w-2xl mx-auto p-4 pb-12">
        {page === 'dashboard' && <Dashboard />}
        {page === 'chart' && <Chart />}
        {page === 'analytics' && <Analytics />}
        {page === 'settings' && <Settings />}
      </main>
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
