"""Exception hierarchy for the adaptive learning AI pipeline.

All pipeline-specific exceptions inherit from PipelineError, allowing
callers to catch the entire hierarchy with a single except clause.
"""


class PipelineError(Exception):
    """Base class for all pipeline-specific errors.

    Catch this to handle any failure from any pipeline stage.
    """


class AudioExtractionError(PipelineError):
    """Raised by audio_extractor when ffmpeg fails or produces zero-duration output.

    Conditions:
    - ffmpeg exits with a non-zero exit code.
    - ffmpeg exits successfully but the extracted WAV file has a duration of zero seconds.
    """


class TranscriptionError(PipelineError):
    """Raised by transcriber when the Groq Whisper API fails or returns no segments.

    Conditions:
    - The Groq API returns an error on all three retry attempts.
    - The API returns a response containing zero transcript segments.
    """


class TopicDetectionError(PipelineError):
    """Raised by topic_detector when LLM topic detection fails.

    Conditions:
    - All three LLM retry attempts return a response that fails JSON validation.
    - After end-time snapping, the resulting end times are not strictly ascending.
    """


class QuestionGenerationError(PipelineError):
    """Raised by question_generator when LLM question generation fails.

    Conditions:
    - All three LLM retry attempts fail validation or time out (30-second timeout).
    """


class OutputWriteError(PipelineError):
    """Raised by output_writer when writing the final JSON file fails.

    Conditions:
    - Any OSError or IOError occurs while writing the output file.
    """


class ConfigurationError(PipelineError):
    """Raised by pipeline_service when required environment variables are missing.

    Conditions:
    - GROQ_API_KEY is absent from the environment or set to an empty string.
    """
