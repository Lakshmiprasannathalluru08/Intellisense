# Product Overview

Real-time learning assessment with adaptive video playback. Teacher uploads a video (no timestamps entered). AI transcribes it (Whisper via Groq) and finds the 4 main topics. When the teacher finishes a topic, the video pauses and shows ONE multiple-choice question. Correct: continue. Wrong: jump back to the start of that topic, replay, then ask a DIFFERENT question. No answer in 60 seconds counts as wrong. After 3 wrong tries, continue and mark the topic weak. Students cannot skip ahead past an unanswered topic. The correct answer is never sent to the browser.
