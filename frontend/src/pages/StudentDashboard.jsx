import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { listVideos } from '../api.js'
import './Dashboard.css'

const SUBJECTS = ['Mathematics', 'Science', 'Computer Science', 'English', 'History', 'Other']

export default function StudentDashboard() {
  const { token, logout } = useAuth()
  const navigate = useNavigate()
  const [videos, setVideos] = useState([])
  const [filter, setFilter] = useState('All')

  useEffect(() => {
    listVideos(token).then(setVideos).catch(() => {})
  }, [token])

  const filtered = filter === 'All' ? videos : videos.filter((v) => v.subject === filter)

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Student Dashboard</h1>
        <div className="header-actions">
          <button className="logout-btn" onClick={() => navigate('/results')}>My Results</button>
          <button className="logout-btn" onClick={handleLogout}>Log out</button>
        </div>
      </header>
      <main className="dashboard-body">
        <div className="filter-row">
          <label>
            Subject
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="All">All</option>
              {SUBJECTS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="video-list">
          {filtered.map((v) => (
            <div key={v.id} className="video-card">
              <div className="video-card-head">
                <h3>{v.title}</h3>
                <span className="video-subject-tag">{v.subject}</span>
              </div>
              {v.description && <p className="video-desc">{v.description}</p>}
              <p className="video-meta">Teacher: {v.teacher_name}</p>
              <button className="watch-btn" onClick={() => navigate(`/watch/${v.id}`)}>
                Watch
              </button>
            </div>
          ))}
          {filtered.length === 0 && <p className="muted">No videos available.</p>}
        </div>
      </main>
    </div>
  )
}
