import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { getMyResults } from '../api.js'
import './Dashboard.css'

export default function MyResults() {
  const { token, logout } = useAuth()
  const navigate = useNavigate()
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getMyResults(token)
      .then(setResults)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [token])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>My Results</h1>
        <div className="header-actions">
          <button className="logout-btn" onClick={() => navigate('/student')}>← Back</button>
          <button className="logout-btn" onClick={handleLogout}>Log out</button>
        </div>
      </header>
      <main className="dashboard-body">
        {loading && <p className="muted">Loading…</p>}
        {error && <div className="form-error">{error}</div>}

        {!loading && results.length === 0 && !error && (
          <p className="muted">You haven't answered any questions yet.</p>
        )}

        {results.length > 0 && (
          <div className="results-table-wrap">
            <table className="results-table">
              <thead>
                <tr>
                  <th>Video</th>
                  <th>Answered</th>
                  <th>Correct (1st try)</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i}>
                    <td>{r.video_title}</td>
                    <td>{r.answered}</td>
                    <td>{r.correct_first_try}</td>
                    <td>{r.score_percent}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  )
}
