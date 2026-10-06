import argparse

from app.config import get_settings
from app.knowledge_base import KnowledgeBase


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a Bedrock knowledge base data source sync.")
    parser.parse_args()
    settings = get_settings()
    knowledge_base = KnowledgeBase(
        region=settings.aws_region,
        knowledge_base_id=settings.knowledge_base_id,
        data_source_id=settings.knowledge_base_data_source_id,
    )
    try:
        print(knowledge_base.run().model_dump_json(indent=2))
    finally:
        knowledge_base.close()


if __name__ == "__main__":
    main()
