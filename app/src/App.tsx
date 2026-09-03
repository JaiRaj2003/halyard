import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import AccountPage from './pages/AccountPage'
import IntakePage from './pages/IntakePage'
import LeadershipPage from './pages/LeadershipPage'
import QueuePage from './pages/QueuePage'
import RequestPage from './pages/RequestPage'

function Tab({ to, children }: { to: string; children: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? 'bg-ink text-white' : 'text-muted hover:bg-slate-100 hover:text-ink'}`
      }
    >
      {children}
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <NavLink to="/intake" className="text-base font-semibold tracking-tight">
            Halyard
          </NavLink>
          <p className="hidden text-xs text-muted lg:block">warm introduction operations</p>
          <nav className="ml-auto flex gap-1">
            <Tab to="/intake">New request</Tab>
            <Tab to="/queue">Queue</Tab>
            <Tab to="/leadership">Leadership</Tab>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">
        <Routes>
          <Route path="/" element={<Navigate to="/intake" replace />} />
          <Route path="/intake" element={<IntakePage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/leadership" element={<LeadershipPage />} />
          <Route path="/requests/:requestId" element={<RequestPage />} />
          <Route path="/accounts/:accountId" element={<AccountPage />} />
        </Routes>
      </main>
    </div>
  )
}
