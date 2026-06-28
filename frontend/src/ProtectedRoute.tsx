import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'

export default function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        加载中…
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return (
    <Layout>
      <Outlet />
    </Layout>
  )
}
