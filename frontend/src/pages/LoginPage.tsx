import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import BrandMark from '../components/BrandMark'

export default function LoginPage() {
  const { login, register } = useAuth()
  const nav = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('demo@example.com')
  const [password, setPassword] = useState('demo123456')
  const [name, setName] = useState('作者')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (mode === 'login') await login(email, password)
      else await register(email, password, name)
      nav('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-900 via-brand-700 to-slate-900">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col justify-center px-4 py-12 lg:flex-row lg:items-center lg:gap-16">
        <div className="mb-10 text-white lg:mb-0 lg:flex-1">
          <div className="mb-6">
            <BrandMark
              variant="logo"
              className="h-14 w-auto max-w-full rounded-xl shadow-lg ring-1 ring-white/10"
            />
          </div>
          <h1 className="text-4xl font-bold leading-tight lg:text-5xl">
            小说 AI 写作台
          </h1>
          <p className="mt-4 max-w-lg text-lg text-brand-100">
            规约驱动 · 章节生成 · 规则 lint · 一键导出。把《我的AI成精了》的写作流程产品化，无需 Cursor 或命令行。
          </p>
          <ul className="mt-8 space-y-2 text-brand-100">
            <li>✦ DeepSeek 流式章节生成</li>
            <li>✦ 逗号/破折号/字数规则引擎（离线可用）</li>
            <li>✦ 角色卡 + 大纲 + 章节规划一体化</li>
          </ul>
        </div>

        <div className="card w-full max-w-md p-8 lg:flex-shrink-0">
          <h2 className="text-xl font-semibold">{mode === 'login' ? '登录' : '注册'}</h2>
          <p className="mt-1 text-sm text-slate-500">演示账号：demo@example.com / demo123456</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === 'register' && (
              <div>
                <label className="label">昵称</label>
                <input className="input" value={name} onChange={e => setName(e.target.value)} />
              </div>
            )}
            <div>
              <label className="label">邮箱</label>
              <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
            </div>
            <div>
              <label className="label">密码</label>
              <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={6} />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button type="submit" className="btn-primary w-full" disabled={loading}>
              {loading ? '请稍候…' : mode === 'login' ? '登录' : '注册'}
            </button>
          </form>
          <p className="mt-4 text-center text-sm text-slate-500">
            {mode === 'login' ? (
              <>还没有账号？<button className="text-brand-600 hover:underline" onClick={() => setMode('register')}>注册</button></>
            ) : (
              <>已有账号？<button className="text-brand-600 hover:underline" onClick={() => setMode('login')}>登录</button></>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}
