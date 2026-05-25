import logging
import threading

import pandas as pd

from config import DATASET_CONFIGS
from database import DatabaseManager
from data_processor import DataProcessor
from web_scraper import WebScraper

logger = logging.getLogger(__name__)


class CricketService:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.data_processor = DataProcessor(self.db_manager)
        self._lock = threading.Lock()

    def scrape_and_process(self, dataset_type: str) -> pd.DataFrame:
        if dataset_type not in DATASET_CONFIGS:
            raise ValueError(f"Invalid dataset type '{dataset_type}'. "
                             f"Choose from: {list(DATASET_CONFIGS)}")

        config = DATASET_CONFIGS[dataset_type]

        with self._lock:
            logger.info(f"Starting scrape for '{dataset_type}'")

            latest = self.db_manager.fetch_latest_date(dataset_type)
            start_date = (
                WebScraper.format_date_for_url(latest.strftime("%Y-%m-%d"))
                if latest else "13+Aug+2022"
            )

            scraper = WebScraper()
            raw_data = scraper.scrape_dataset(dataset_type, start_date)

            if not raw_data:
                logger.warning(f"No new data scraped for '{dataset_type}'")
                return pd.DataFrame()

            processors = {
                "team": self.data_processor.process_team_data,
                "batting": self.data_processor.process_batting_data,
                "bowling": self.data_processor.process_bowling_data,
            }
            df = processors[dataset_type](raw_data, config["columns"])
            logger.info(f"'{dataset_type}' scrape complete – {len(df)} rows processed")
            return df
