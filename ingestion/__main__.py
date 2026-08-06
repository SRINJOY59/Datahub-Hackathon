"""Entry point:  python -m ingestion"""
from ingestion.runner import IngestionRunner

if __name__ == "__main__":
    IngestionRunner().run()
