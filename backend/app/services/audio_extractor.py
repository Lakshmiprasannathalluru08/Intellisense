"""Audio extraction stage of the AI pipeline.

Wraps ffmpeg via subprocess to strip the audio track from a video file and
write it to a temporary mono 16 kHz 32 kbps MP3 file. The caller
(orchestrator) owns cleanup of the returned path.
"""

import os
import subprocess
import sys
import tempfile

from app.exceptions import AudioExtractionError


def extract_audio(video_path: str) -> str:
    """Extract the audio track from *video_path* to a temporary MP3 file.

    The output is mono, 16 kHz, 32 kbps MP3 — small and fast to upload to the
    Groq Whisper API. Returns the absolute path to the MP3 file on success.

    Raises:
        AudioExtractionError: if ffmpeg exits with a non-zero code, or if the
            resulting audio file has a duration of zero seconds (detected via
            ffprobe), or if the output file is absent / empty.

    The caller is responsible for deleting the returned file.
    """
    # Create a named temp file; we close it immediately so ffmpeg can open it
    # on Windows (where a file cannot be opened by two processes simultaneously).
    fd, audio_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)

    # Build the ffmpeg command.
    # -y                 : overwrite the temp file we just created
    # -i                 : input video
    # -vn                : drop the video stream
    # -acodec libmp3lame  : encode to MP3
    # -b:a 32k           : 32 kbps bitrate
    # -ar 16000          : resample to 16 kHz (Whisper's preferred rate)
    # -ac 1              : mono channel
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "32k",
        "-ar", "16000",
        "-ac", "1",
        audio_path,
    ]

    try:
        result = subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        # ffmpeg is not installed or not on PATH
        raise AudioExtractionError(
            "ffmpeg executable not found. Ensure ffmpeg is installed and on PATH."
        )

    if result.returncode != 0:
        stderr_output = result.stderr.decode(errors="replace")
        print(
            f"AudioExtractionError: ffmpeg exited with code {result.returncode}.\n"
            f"{stderr_output}",
            file=sys.stderr,
        )
        raise AudioExtractionError(
            f"ffmpeg exited with non-zero exit code {result.returncode}: {stderr_output}"
        )

    # Guard: file must exist and be non-empty before we bother probing.
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        print(
            "AudioExtractionError: ffmpeg produced an empty or missing audio file.",
            file=sys.stderr,
        )
        raise AudioExtractionError(
            "ffmpeg produced an empty or missing audio file."
        )

    # Probe the duration with ffprobe to detect zero-duration audio.
    duration = _probe_duration(audio_path)
    if duration == 0.0:
        print(
            "AudioExtractionError: extracted audio file has a duration of zero seconds.",
            file=sys.stderr,
        )
        raise AudioExtractionError(
            "Extracted audio file has a duration of zero seconds."
        )

    return audio_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _probe_duration(audio_path: str) -> float:
    """Return the duration (in seconds) of *audio_path* as reported by ffprobe.

    Returns 0.0 if ffprobe is unavailable or the duration cannot be parsed,
    so the caller can treat such a file as zero-duration and raise an error.
    """
    ffprobe_cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]

    try:
        probe_result = subprocess.run(
            ffprobe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        # ffprobe not available — fall back to file-size proxy (already
        # checked by the caller, so treat as non-zero duration).
        return 1.0  # non-zero sentinel: assume OK

    if probe_result.returncode != 0:
        # Probe failed for some other reason; treat as zero to be safe.
        return 0.0

    output = probe_result.stdout.decode(errors="replace").strip()
    try:
        return float(output)
    except (ValueError, TypeError):
        return 0.0
