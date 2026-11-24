"""Stage 5: JSON persistence for the adaptive learning AI pipeline.

Writes a PipelineOutput dataclass to disk atomically: first to a `.tmp`
sibling file, then renamed into place via os.replace.  Any I/O failure
raises OutputWriteError.
"""

import dataclasses
import json
import os

from app.exceptions import OutputWriteError
from app.models import PipelineOutput


def write_output(result: PipelineOutput, output_path: str) -> None:
    """Serialise *result* to JSON and write it atomically to *output_path*.

    The write is atomic on POSIX systems and best-effort atomic on Windows:
    the data is first written to ``<output_path>.tmp``, then
    ``os.replace`` renames it to the final path in a single syscall.

    Args:
        result:      The completed pipeline output to persist.
        output_path: Destination path for the JSON file.

    Raises:
        OutputWriteError: On any ``OSError`` / ``IOError`` that occurs
            during serialisation, file creation, write, or rename.
    """
    tmp_path = output_path + ".tmp"
    try:
        payload = dataclasses.asdict(result)
        json_text = json.dumps(payload, indent=2, ensure_ascii=False)
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(json_text)
        os.replace(tmp_path, output_path)
    except (OSError, IOError) as exc:
        # Best-effort cleanup of the temp file; ignore secondary errors.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise OutputWriteError(
            f"Failed to write pipeline output to {output_path!r}: {exc}"
        ) from exc
