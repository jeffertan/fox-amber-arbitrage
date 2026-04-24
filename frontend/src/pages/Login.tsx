import { useState } from 'react'
import { useAuth } from '../AuthContext'
import { api } from '../api'

export default function Login() {
  const { login } = useAuth()
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    setLoading(true)
    try {
      const data = await api.login(pw)
      if (data.access_token) { login(data.access_token) }
      else setErr('登录失败，请检查密码')
    } catch { setErr('服务器连接失败') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo area */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-950 border border-blue-800/50 rounded-2xl mb-4">
            <span className="text-3xl">⚡</span>
          </div>
          <h1 className="text-white text-xl font-bold">Fox-Amber 控制台</h1>
          <p className="text-gray-500 text-sm mt-1">电价套利监控系统</p>
        </div>

        <form onSubmit={submit} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 space-y-4 shadow-2xl">
          <div>
            <label className="text-gray-400 text-xs font-medium block mb-1.5">密码</label>
            <input
              type="password"
              placeholder="输入访问密码"
              value={pw}
              onChange={e => setPw(e.target.value)}
              className="w-full bg-gray-800 text-white rounded-xl px-4 py-3 outline-none border border-gray-700 focus:border-blue-500 transition-colors placeholder-gray-600"
              autoFocus
            />
          </div>
          {err && (
            <div className="bg-red-950/60 border border-red-800/50 rounded-xl px-3 py-2 text-red-300 text-sm">
              {err}
            </div>
          )}
          <button
            type="submit"
            disabled={loading || !pw}
            className="w-full bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl py-3 font-semibold transition-colors"
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
