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
    } catch { setErr('服务器错误') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <form onSubmit={submit} className="bg-gray-900 p-8 rounded-2xl w-80 space-y-4 shadow-xl">
        <div className="text-center">
          <div className="text-3xl mb-2">⚡</div>
          <h1 className="text-white text-xl font-semibold">Fox-Amber 控制台</h1>
          <p className="text-gray-500 text-sm mt-1">电价套利监控系统</p>
        </div>
        <input
          type="password"
          placeholder="密码"
          value={pw}
          onChange={e => setPw(e.target.value)}
          className="w-full bg-gray-800 text-white rounded-lg px-4 py-2.5 outline-none border border-gray-700 focus:border-blue-500 transition-colors"
          autoFocus
        />
        {err && <p className="text-red-400 text-sm text-center">{err}</p>}
        <button
          type="submit"
          disabled={loading || !pw}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg py-2.5 font-medium transition-colors"
        >
          {loading ? '登录中...' : '登录'}
        </button>
      </form>
    </div>
  )
}
