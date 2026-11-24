import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { deleteVideo, listVideos, uploadVideo } from '../api.js'
import './Dashboard.css'

const SUBJECTS = ['Mathematics', 'Science', 'Computer Science', 'English', 'History', 'Other']
const TERMINAL = new Set(['ready', 'failed'])

export default function TeacherDashboard() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [subject, setSubject] = useState('Mathematics')
  const [description, setDescription] = useState('')
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [videos, setVideos] = useState([])
  const [polling, setPolling] = useState(true)

  const fetchVideos = useCallback(async () => {
    try {
      const data = await listVideos(token)
      setVideos(data)
      // Stop polling once every visible video has reached a terminal state.
      const allTerminal = data.length > 0 && data.every((v) => TERMINAL.has(v.status))
      setPolling(!allTerminal)
    } catch {
      // keep polling on transient errors
    }
  }, [token])

  useEffect(() => {
    fetchVideos()
  }, [fetchVideos])

  useEffect(() => {
    if (!polling) return
    const id = setInterval(fetchVideos, 5000)
    return () => clearInterval(id)
  }, [polling, fetchVideos])

  async function handleUpload(e) {
    e.preventDefault()
    setError('')
    if (!file) {
      setError('Please choose a video file.')
      return
    }
    setUploading(true)
    setProgress(0)
    try {
      await uploadVideo({
        file,
        title,
        subject,
        description,
        token,
        onProgress: setProgress,
      })
      setTitle('')
      setSubject('Mathematics')
      setDescription('')
      setFile(null)
      setPolling(true)
      fetchVideos()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(videoId) {
    if (!window.confirm('Delete this video? This cannot be undone.')) return
    try {
      await deleteVideo(videoId, token)
      setVideos((prev) => prev.filter((v) => v.id !== videoId))
    } catch (err) {
      setError(err.message)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Teacher Dashboard</h1>
        <button className="logout-btn" onClick={handleLogout}>Log out</button>
      </header>
      <main className="dashboard-body">
        <form className="upload-form" onSubmit={handleUpload}>
          <h2>Upload a video</h2>
          {error && <div className="form-error">{error}</div>}
          <label>
            Title
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </label>
          <label>
            Subject
            <select value={subject} onChange={(e) => setSubject(e.target.value)}>
              {SUBJECTS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Description
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={500}
            />
          </label>
          <label>
            Video file
            <input
              type="file"
              accept="video/*"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              required
            />
          </label>
          {uploading && (
            <div className="progress-wrap">
              <div className="progress-bar" style={{ width: `${progress}%` }} />
              <span className="progress-text">{progress}%</span>
            </div>
          )}
          <button type="submit" className="upload-btn" disabled={uploading}>
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </form>

        <h2 className="section-title">My videos</h2>
        {videos.length === 0 ? (
          <p className="muted">No videos yet.</p>
        ) : (
          <div className="video-list">
            {videos.map((v) => (
              <VideoCard key={v.id} video={v} onDelete={() => handleDelete(v.id)} onResults={() => navigate(`/teacher/results/${v.id}`)} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

function VideoCard({ video, onDelete, onResults }) {
  return (
    <div className="video-card">
      <div className="video-card-head">
        <h3>{video.title}</h3>
        <span className={`status-badge status-${video.status}`}>{video.status}</span>
      </div>
      <p className="video-subject">{video.subject}</p>
      {video.description && <p className="video-desc">{video.description}</p>}
      <p className="video-meta">
        {video.status === 'ready' ? null : 'Processing…'}
      </p>
      {video.status === 'failed' && video.error && (
        <p className="video-error">{video.error}</p>
      )}
      {video.status === 'ready' && (
        <button className="results-btn" onClick={onResults}>Results</button>
      )}
      <button className="delete-btn" onClick={onDelete}>Delete</button>
    </div>
  )
}
