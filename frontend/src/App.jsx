import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import BottomNav from './components/BottomNav.jsx'
import InstallPrompt from './components/InstallPrompt.jsx'
import OfflineBanner from './components/OfflineBanner.jsx'
import { useAuth } from './context/AuthContext.jsx'
import DocumentEditor from './pages/DocumentEditor.jsx'
import History from './pages/History.jsx'
import JobDetail from './pages/JobDetail.jsx'
import Jobs from './pages/Jobs.jsx'
import Login from './pages/Login.jsx'
import Profile from './pages/Profile.jsx'
import SavedJobs from './pages/SavedJobs.jsx'
import Signup from './pages/Signup.jsx'

function RequireAuth({ children }) {
  const { user, booting } = useAuth()
  const location = useLocation()

  if (booting) return <div className="boot">Loading…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}

const PROTECTED = [
  ['/', Jobs],
  ['/jobs/:jobId', JobDetail],
  ['/saved', SavedJobs],
  ['/history', History],
  ['/documents/:documentId', DocumentEditor],
  ['/profile', Profile],
]

export default function App() {
  const { user } = useAuth()

  return (
    <div className="app">
      <OfflineBanner />
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/signup" element={user ? <Navigate to="/" replace /> : <Signup />} />

        {PROTECTED.map(([path, Page]) => (
          <Route
            key={path}
            path={path}
            element={
              <RequireAuth>
                <Page />
              </RequireAuth>
            }
          />
        ))}

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {user && <InstallPrompt />}
      {user && <BottomNav />}
    </div>
  )
}
