import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { getQuestion, getTopics, postAnswer } from '../api.js'
import './Dashboard.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
// Seconds after the last word of a topic ends before the question pops up.
// Also the grace window on onEnded for the last topic.
const BUFFER = 0.8

export default function Watch() {
  const { id } = useParams()
  const { token, logout } = useAuth()
  const navigate = useNavigate()

  const videoRef = useRef(null)
  const topicsRef = useRef([])    // {index, start, end, noQuestions?}
  const currentRef = useRef(0)   // index INTO topicsRef of the current popup topic
  const tryRef = useRef(1)
  const answeredRef = useRef(false)
  const maxAllowedRef = useRef(Infinity)
  const lastValidRef = useRef(0)
  const activeQRef = useRef(null)
  const phaseRef = useRef('loading')

  const [phase, setPhase] = useState('loading')
  const [popup, setPopup] = useState(null)
  const [feedback, setFeedback] = useState(null)
  const [error, setError] = useState('')

  const setPhaseBoth = (p) => { phaseRef.current = p; setPhase(p) }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  // Find the index (into topicsRef) of the next topic that has questions,
  // starting from `from`.  Returns -1 if none remain.
  const nextPopupIdx = (from) => {
    const t = topicsRef.current
    for (let i = from; i < t.length; i++) {
      if (!t[i].noQuestions) return i
    }
    return -1
  }

  // ---------------------------------------------------------------------------
  // Question lifecycle
  // ---------------------------------------------------------------------------

  const triggerQuestion = async () => {
    const v = videoRef.current
    if (v) v.pause()
    // Set phaseRef synchronously before any await so onTimeUpdate / onPlay
    // see 'question' and refuse to play.
    phaseRef.current = 'question'
    setFeedback(null)
    setPopup(null)
    setPhase('question')   // re-render: controls = false

    try {
      const q = await getQuestion(id, currentRef.current, tryRef.current, token)
      // Re-pause in case anything tried to play during the fetch.
      if (videoRef.current) videoRef.current.pause()
      activeQRef.current = q
      setPopup(q)
    } catch (e) {
      // 404 means this topic has no questions — mark it and resume playing.
      if (e.message && (e.message.includes('404') || e.message.toLowerCase().includes('no question'))) {
        const idx = currentRef.current
        topicsRef.current = topicsRef.current.map((t, i) =>
          i === idx ? { ...t, noQuestions: true } : t
        )
        // Advance to the next popup topic and resume.
        _advanceSeekLimitFrom(idx + 1)
        setPhaseBoth('playing')
        if (videoRef.current) videoRef.current.play().catch(() => {})
      } else {
        setError(e.message)
        setPhaseBoth('playing')
      }
    }
  }

  // Update seek limit to cover up to the next popup topic (or lift entirely).
  // `fromIdx` is the topicsRef index to start searching from.
  const _advanceSeekLimitFrom = (fromIdx) => {
    const next = nextPopupIdx(fromIdx)
    if (next === -1) {
      maxAllowedRef.current = Infinity
    } else {
      currentRef.current = next
      tryRef.current = 1
      answeredRef.current = false
      maxAllowedRef.current = topicsRef.current[next].end + BUFFER
    }
  }

  // ---------------------------------------------------------------------------
  // After answering: show feedback, then wait for Continue
  // ---------------------------------------------------------------------------

  const handleResult = (res) => {
    if (res.result === 'correct') {
      setFeedback({
        result: 'correct',
        explanation: res.explanation,
        correct_answer: res.correct_answer,
        _correct: true,
        _weak: false,
        _next_action: 'continue',
      })
    } else {
      setFeedback({
        result: 'wrong',
        explanation: res.explanation,
        correct_answer: res.correct_answer,
        _correct: false,
        _weak: res.weak,
        _next_action: res.next_action,
      })
    }
    // No auto-advance timer — only the Continue button moves forward.
    setPhaseBoth('feedback')
  }

  const submitAnswer = async (selected_index) => {
    const q = activeQRef.current
    if (!q) return
    try {
      const res = await postAnswer({
        video_id: id,
        topic_index: currentRef.current,
        question_index: q.question_index,
        selected_index,
        try_number: tryRef.current,
        token,
      })
      handleResult(res)
    } catch (e) {
      setError(e.message)
      setPhaseBoth('playing')
    }
  }

  // ---------------------------------------------------------------------------
  // Continue button — the ONLY way to move forward after a feedback card
  // ---------------------------------------------------------------------------

  const handleContinue = () => {
    const fb = feedback
    if (!fb) return
    setPopup(null)
    setFeedback(null)
    activeQRef.current = null

    const c = currentRef.current
    const t = topicsRef.current
    const v = videoRef.current

    const isLastPopup = nextPopupIdx(c + 1) === -1
    const shouldAdvance = fb._correct || (fb._next_action === 'continue' && fb._weak)

    if (shouldAdvance) {
      if (isLastPopup) {
        // Last pop-up answered: show finish message, do not play.
        setPhaseBoth('finished')
      } else {
        // Advance seek limit to the next popup topic, resume from current pos.
        _advanceSeekLimitFrom(c + 1)
        setPhaseBoth('playing')
        if (v) v.play().catch(() => {})
      }
    } else {
      // Wrong with tries left: seek back to the START of this topic, replay.
      tryRef.current += 1
      answeredRef.current = false
      // Update limit BEFORE seeking so the guard doesn't block the backward seek.
      maxAllowedRef.current = t[c].end + BUFFER
      setPhaseBoth('playing')
      if (v) {
        v.currentTime = t[c].start
        v.play().catch(() => {})
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Video event handlers
  // ---------------------------------------------------------------------------

  const onTimeUpdate = () => {
    if (phaseRef.current !== 'playing') return
    const v = videoRef.current
    if (!v) return
    const now = v.currentTime
    const tpc = topicsRef.current
    const c = currentRef.current
    if (c >= tpc.length) return
    const topic = tpc[c]
    // Only trigger for topics that haven't been flagged as having no questions.
    if (!topic.noQuestions && !answeredRef.current && now >= topic.end + BUFFER && now >= topic.start) {
      answeredRef.current = true
      triggerQuestion()
      return
    }
    if (now <= maxAllowedRef.current) lastValidRef.current = now
  }

  const onSeeking = () => {
    const v = videoRef.current
    if (!v) return
    if (v.currentTime > maxAllowedRef.current) {
      v.currentTime = lastValidRef.current
    }
  }

  // If anything tries to play while a question/feedback is open, re-pause.
  const onPlay = () => {
    const p = phaseRef.current
    if (p === 'question' || p === 'feedback') {
      const v = videoRef.current
      if (v) v.pause()
    }
  }

  const onEnded = () => {
    // Backup trigger for the last topic: because the last topic ends at the
    // video end, the video stops before currentTime reaches end + BUFFER.
    // If we're still playing and the current topic hasn't been answered, ask
    // the question now.
    if (phaseRef.current === 'playing') {
      const tpc = topicsRef.current
      const c = currentRef.current
      if (tpc.length > 0 && c < tpc.length && !tpc[c].noQuestions && !answeredRef.current) {
        answeredRef.current = true
        triggerQuestion()
        return
      }
    }
    // Video ended with no pending question: show finish (unless a card is open).
    if (phaseRef.current !== 'question' && phaseRef.current !== 'feedback') {
      setPhaseBoth('finished')
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  // ---------------------------------------------------------------------------
  // Setup
  // ---------------------------------------------------------------------------

  const videoSrc = `${API_URL}/videos/${id}/file?token=${encodeURIComponent(token || '')}`

  useEffect(() => {
    let active = true
    setError('')
    getTopics(id, token)
      .then((data) => {
        if (!active) return
        const t = (data || []).map((topic) => ({ ...topic }))
        topicsRef.current = t

        // Set the initial seek limit and current popup topic.
        // We don't pre-fetch questions here (would create served_question entries).
        // Topics are optimistically assumed to have questions until getQuestion 404s.
        if (t.length > 0) {
          currentRef.current = 0
          maxAllowedRef.current = t[0].end + BUFFER
          lastValidRef.current = t[0].start
        } else {
          maxAllowedRef.current = Infinity
        }
        setPhaseBoth('playing')
      })
      .catch((e) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [id, token])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Hide native controls while a question or feedback card is open so the
  // student can't press Play underneath the overlay.
  const showControls = phase !== 'question' && phase !== 'feedback'

  return (
    <div className="dashboard watch-page">
      <header className="dashboard-header">
        <h1>Watch</h1>
        <button className="logout-btn" onClick={handleLogout}>Log out</button>
      </header>
      <main className="dashboard-body">
        {error && <div className="form-error">{error}</div>}

        <div className="player-wrap">
          <video
            ref={videoRef}
            src={videoSrc}
            controls={showControls}
            onTimeUpdate={onTimeUpdate}
            onSeeking={onSeeking}
            onPlay={onPlay}
            onEnded={onEnded}
            className="player-video"
          />

          {phase === 'question' && popup && (
            <div className="popup-overlay">
              <div className="popup-card">
                <h3 className="popup-prompt">{popup.prompt}</h3>
                <div className="popup-options">
                  {popup.options.map((opt, i) => (
                    <button
                      key={i}
                      className="popup-option"
                      onClick={() => submitAnswer(i)}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {phase === 'feedback' && feedback && (
            <div className="popup-overlay">
              <div className={`popup-card feedback-card feedback-${feedback.result}`}>
                {feedback.result === 'correct' ? (
                  <>
                    <h3 className="feedback-title correct">Correct!</h3>
                    <p className="feedback-explanation">{feedback.explanation}</p>
                  </>
                ) : (
                  <>
                    <h3 className="feedback-title wrong">Not quite</h3>
                    {feedback.correct_answer && (
                      <p className="feedback-correct-answer">
                        Correct answer: <strong>{feedback.correct_answer}</strong>
                      </p>
                    )}
                    <p className="feedback-explanation">{feedback.explanation}</p>
                  </>
                )}
                <button className="feedback-continue-btn" onClick={handleContinue}>
                  Continue
                </button>
              </div>
            </div>
          )}

          {phase === 'finished' && (
            <div className="popup-overlay">
              <div className="popup-card feedback-card">
                <h3>You've completed the video!</h3>
                <button className="watch-btn" onClick={() => navigate('/student')}>
                  Back to dashboard
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
