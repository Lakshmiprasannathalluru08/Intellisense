import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { getVideoResults } from '../api.js'
import './Dashboard.css'

export default function Results() {
  const { videoId } = useParams()
  const { token, logout } = useAuth()
  const navigate = useNavigate()

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('score_percent')
  const [sortAsc, setSortAsc] = useState(false)

  useEffect(() => {
    setLoading(true)
    getVideoResults(videoId, token)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [videoId, token])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  function toggleSort(key) {
    if (sortKey === key) setSortAsc((a) => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  const sorted = data?.per_student
    ? [...data.per_student].sort((a, b) => {
        const av = a[sortKey] ?? 0
        const bv = b[sortKey] ?? 0
        const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
        return sortAsc ? cmp : -cmp
      })
    : []

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Video Results</h1>
        <div className="header-actions">
          <button className="logout-btn" onClick={() => navigate('/teacher')}>← Back</button>
          <button className="logout-btn" onClick={handleLogout}>Log out</button>
        </div>
      </header>
      <main className="dashboard-body">
        {loading && <p className="muted">Loading…</p>}
        {error && <div className="form-error">{error}</div>}

        {data && (
          <>
            {/* Summary cards */}
            <div className="results-summary">
              <div className="results-card">
                <div className="results-card-num">{data.students_attempted}</div>
                <div className="results-card-label">Students attempted</div>
              </div>
              <div className="results-card">
                <div className="results-card-num">{data.average_score}%</div>
                <div className="results-card-label">Average score</div>
              </div>
            </div>

            {data.students_attempted === 0 ? (
              <p className="muted results-empty">No student has answered yet.</p>
            ) : (
              <>
                {/* Bar chart */}
                <h2 className="section-title">Score per student</h2>
                <div className="bar-chart">
                  {sorted.map((s, i) => (
                    <div key={i} className="bar-row">
                      <div className="bar-label" title={s.student_name}>
                        {s.student_name.length > 20 ? s.student_name.slice(0, 18) + '…' : s.student_name}
                      </div>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{ width: `${s.score_percent}%` }}
                        />
                      </div>
                      <div className="bar-value">{s.score_percent}%</div>
                    </div>
                  ))}
                </div>

                {/* Students table */}
                <h2 className="section-title">Students</h2>
                <div className="results-table-wrap">
                  <table className="results-table">
                    <thead>
                      <tr>
                        <th className="sortable" onClick={() => toggleSort('student_name')}>
                          Name {sortKey === 'student_name' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th>Answered</th>
                        <th>Correct (1st try)</th>
                        <th className="sortable" onClick={() => toggleSort('score_percent')}>
                          Score {sortKey === 'score_percent' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th>Last activity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.map((s, i) => (
                        <tr key={i}>
                          <td>{s.student_name}</td>
                          <td>{s.answered}</td>
                          <td>{s.correct_first_try}</td>
                          <td>{s.score_percent}%</td>
                          <td>{s.last_activity ? new Date(s.last_activity).toLocaleString() : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Questions table */}
                <h2 className="section-title">Questions</h2>
                <div className="results-table-wrap">
                  <table className="results-table">
                    <thead>
                      <tr>
                        <th>Question</th>
                        <th>Times shown</th>
                        <th>% Correct</th>
                        <th>Most chosen wrong answer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.per_question.map((q, i) => (
                        <tr key={i} className={q.correct_percent < 50 ? 'row-hard' : ''}>
                          <td>{q.question_text}</td>
                          <td>{q.times_shown}</td>
                          <td>{q.correct_percent}%</td>
                          <td>{q.most_chosen_wrong_option_text || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
