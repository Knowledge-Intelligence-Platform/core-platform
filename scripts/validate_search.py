import argparse

from app.config import get_settings
from app.main import build_application, configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Bedrock knowledge query.")
    parser.add_argument("question")
    arguments = parser.parse_args()
    configure_logging()
    application = build_application(get_settings())
    try:
        result = application.agent.answer(arguments.question)
        print(result.model_dump_json(indent=2))
    finally:
        application.knowledge_base.close()


if __name__ == "__main__":
    main()
