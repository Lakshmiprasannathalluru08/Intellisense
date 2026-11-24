// Backend address from VITE_API_URL, defaulting to the local FastAPI server.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  let data = null
  try {
    data = await res.json()
  } catch {
    // response had no JSON body
  }

  if (!res.ok) {
    const message =
      (data && (data.detail || data.message)) || `Request failed (${res.status})`
    throw new Error(message)
  }
  return data
}

export function signup({ name, email, password, role }) {
  return request('/auth/signup', {
    method: 'POST',
    body: { name, email, password, role },
  })
}

export function login({ email, password }) {
  return request('/auth/login', {
    method: 'POST',
    body: { email, password },
  })
}

export function me(token) {
  return request('/auth/me', { token })
}

export function listVideos(token) {
  return request('/videos', { token })
}

// Upload uses XMLHttpRequest so we can report upload progress.
export function uploadVideo({ file, title, subject, description, token, onProgress }) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const formData = new FormData()
    formData.append('title', title)
    formData.append('subject', subject)
    formData.append('description', description)
    formData.append('file', file)

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }
    xhr.onload = () => {
      let data = null
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        // no JSON body
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data)
      } else {
        reject(
          new Error(
            (data && (data.detail || data.message)) ||
              `Upload failed (${xhr.status})`
          )
        )
      }
    }
    xhr.onerror = () => reject(new Error('Network error during upload'))
    xhr.open('POST', `${API_URL}/videos`)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.send(formData)
  })
}

export function getTopics(videoId, token) {
  return request(`/videos/${videoId}/topics`, { token })
}

export function getQuestion(videoId, topicIndex, tryNumber, token) {
  return request(
    `/videos/${videoId}/topics/${topicIndex}/question?try_number=${tryNumber}`,
    { token }
  )
}

export function postAnswer({
  video_id,
  topic_index,
  question_index,
  selected_index,
  try_number,
  timed_out = false,
  token,
}) {
  return request('/answers', {
    method: 'POST',
    token,
    body: { video_id, topic_index, question_index, selected_index, try_number, timed_out },
  })
}

export function deleteVideo(videoId, token) {
  return request(`/videos/${videoId}`, { method: 'DELETE', token })
}

export function getVideoResults(videoId, token) {
  return request(`/results/video/${videoId}`, { token })
}

export function getMyResults(token) {
  return request('/results/me', { token })
}
