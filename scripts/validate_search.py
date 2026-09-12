#!/usr/bin/env python3
"""Run one live, source-grounded Phase 1 search query."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.main import build_application, configure_logging  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question",
        nargs="?",
        default="What is the platform service??",
    )
    arguments = parser.parse_args()

    configure_logging()
    application = build_application(get_settings())
    result = application.agent.answer(arguments.question)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
