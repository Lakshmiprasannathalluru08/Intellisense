"""CLI entry point for the adaptive learning AI pipeline.

Usage:
    python run_pipeline.py <video_path> [--output <output_path>]

Loads GROQ_API_KEY from backend/.env via python-dotenv, runs the full
pipeline through the orchestrator (app.services.pipeline_service.run_pipeline),
prints the resulting JSON to stdout, persists it to a file, and exits
with code 0 on success or a non-zero code on failure (errors to stderr).
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from app.exceptions import PipelineError
from app.services.pipeline_service import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the adaptive learning AI pipeline on a video file."
    )
    parser.add_argument("video_path", help="Path to the input video file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Destination path for the JSON output file. "
             "Defaults to <video_stem>_output.json next to the input video.",
    )
    args = parser.parse_args()

    # Validate the input path exists and is a file.
    if not os.path.exists(args.video_path):
        print(f"Error: input video not found: {args.video_path}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.video_path):
        print(f"Error: not a file: {args.video_path}", file=sys.stderr)
        return 1

    # Derive the default output path from the input file name.
    if args.output is None:
        video_abspath = os.path.abspath(args.video_path)
        stem = os.path.splitext(video_abspath)[0]
        output_path = f"{stem}_output.json"
    else:
        output_path = args.output

    # Load GROQ_API_KEY (and other vars) from backend/.env.
    # override=False so an already-set environment variable takes precedence.
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    try:
        result = run_pipeline(args.video_path, output_path)
    except PipelineError as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    # Print the final JSON to stdout and exit with code 0.
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    print(f"\nOutput saved to: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
