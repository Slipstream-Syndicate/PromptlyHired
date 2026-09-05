import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import BottomNav from './components/BottomNav.jsx'
import InstallPrompt from './components/InstallPrompt.jsx'
import OfflineBanner from './components/OfflineBanner.jsx'
import { useAuth } from './context/AuthContext.jsx'
import Analytics from './pages/Analytics.jsx'
import Applications from './pages/Applications.jsx'
import FollowedCompanies from './pages/FollowedCompanies.jsx'
import Home from './pages/Home.jsx'
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

export default function App() {
  const { user } = useAuth()

  return (
    <div className="app">
      <OfflineBanner />
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/signup" element={user ? <Navigate to="/" replace /> : <Signup />} />

        <Route
          path="/"
          element={
            <RequireAuth>
              <Home />
            </RequireAuth>
          }
        />
        <Route
          path="/saved"
          element={
            <RequireAuth>
              <SavedJobs />
            </RequireAuth>
          }
        />
        <Route
          path="/applications"
          element={
            <RequireAuth>
              <Applications />
            </RequireAuth>
          }
        />
        <Route
          path="/profile"
          element={
            <RequireAuth>
              <Profile />
            </RequireAuth>
          }
        />
        <Route
          path="/profile/analytics"
          element={
            <RequireAuth>
              <Analytics />
            </RequireAuth>
          }
        />
        {/* One tap into Profile rather than a permanent nav slot - it is a
            set-once page that mostly just generates notifications. */}
        <Route
          path="/profile/companies"
          element={
            <RequireAuth>
              <FollowedCompanies />
            </RequireAuth>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {user && <InstallPrompt />}
      {user && <BottomNav />}
    </div>
  )
}
