import re
import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import TEAM_MAPPING

logger = logging.getLogger(__name__)


class DataProcessor:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    # ------------------------------------------------------------------
    # Shared cleaning helpers
    # ------------------------------------------------------------------

    def _clean_raw(self, data: list, min_columns: int) -> np.ndarray:
        cleaned = []
        for row in data:
            if all(isinstance(c, str) for c in row) and len(row) >= min_columns:
                row[0] = TEAM_MAPPING.get(row[0], row[0])
                cleaned.append(row)
        logger.info(f"Cleaned {len(cleaned)} / {len(data)} rows")
        return np.array(cleaned)

    def _to_df(self, arr: np.ndarray, columns: list[str]) -> pd.DataFrame:
        trimmed = [row[: len(columns)] for row in arr]
        df = pd.DataFrame(trimmed, columns=columns)
        empty_cols = [c for c in df.columns if not c.strip()]
        if empty_cols:
            df.drop(columns=empty_cols, inplace=True)
        return df

    @staticmethod
    def _clean_opposition(df: pd.DataFrame) -> pd.DataFrame:
        df["Opposition"] = df["Opposition"].str.replace(r"^v\s*", "", regex=True)
        return df

    @staticmethod
    def _normalize_date(val) -> Optional[str]:
        if pd.isna(val):
            return None
        try:
            if isinstance(val, str):
                dt = pd.to_datetime(val)
            elif isinstance(val, datetime):
                dt = val
            else:
                dt = pd.to_datetime(val)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _split_player_team(df: pd.DataFrame) -> pd.DataFrame:
        def extract_team(name: str) -> Optional[str]:
            m = re.search(r"\((.*?)\)", name)
            return TEAM_MAPPING.get(m.group(1)) if m else None

        def clean_player(name: str) -> str:
            return re.sub(r"\(.*?\)", "", name).strip()

        df["Team"] = df["Player"].apply(extract_team)
        df["Player"] = df["Player"].apply(clean_player)
        return df

    @staticmethod
    def _parse_score(score: str) -> tuple[int, int, int]:
        declared = 0
        wickets = 10
        s = score.strip()
        if "d" in s:
            declared = 1
            s = s.replace("d", "")
        if "/" in s:
            parts = s.split("/")
            return int(parts[0]), int(parts[1]), declared
        return int(s), wickets, declared

    @staticmethod
    def _overs_to_float(val) -> float:
        if not isinstance(val, str):
            return float("nan")
        val = val.strip()
        if "." in val:
            whole, balls = val.split(".")
            return int(whole) + int(balls) / 6
        try:
            return float(val)
        except ValueError:
            return float("nan")

    # ------------------------------------------------------------------
    # Team
    # ------------------------------------------------------------------

    def process_team_data(self, scraped_data: list, columns: list[str]) -> pd.DataFrame:
        logger.info(f"Processing team data – {len(scraped_data)} raw rows")
        arr = self._clean_raw(scraped_data, len(columns))
        df = self._to_df(arr, columns)
        df = self._clean_opposition(df)

        # Score → (runs, wickets, declared)
        parsed = df["ScoreDescending"].apply(self._parse_score)
        df["ScoreDescending"] = parsed.apply(lambda x: x[0])
        df["Wickets"] = parsed.apply(lambda x: x[1])
        df["Declared"] = parsed.apply(lambda x: x[2])

        df["Overs"] = df["Overs"].apply(self._overs_to_float)
        df["RPO"] = df["RPO"].astype(float)
        df["Inns"] = df["Inns"].astype(int)
        df["Lead"] = df["Lead"].fillna(0).astype(int)
        df["Start Date"] = df["Start Date"].apply(
            lambda v: self._normalize_date(pd.to_datetime(v, errors="coerce"))
        )

        records = [
            (
                row["Team"], row["ScoreDescending"], row["Overs"], row["RPO"],
                row["Lead"], row["Inns"], row["Result"], row["Opposition"],
                row["Ground"], row["Start Date"], row["Declared"], row["Wickets"],
            )
            for _, row in df.iterrows()
        ]
        inserted = self.db_manager.bulk_insert_team(records)
        logger.info(f"Team: {inserted} new rows inserted, {len(records) - inserted} duplicates ignored")
        return df

    # ------------------------------------------------------------------
    # Batting
    # ------------------------------------------------------------------

    def process_batting_data(self, scraped_data: list, columns: list[str]) -> pd.DataFrame:
        logger.info(f"Processing batting data – {len(scraped_data)} raw rows")
        arr = self._clean_raw(scraped_data, len(columns))
        df = self._to_df(arr, columns)
        df = self._clean_opposition(df)
        df = self._split_player_team(df)

        # Remove DNS / absent/ sub rows
        df = df[~df["RunsDescending"].isin(["DNB", "absent", "sub", "TDNB"])]

        # Not-out flag
        df["Not Out"] = df["RunsDescending"].str.contains(r"\*", na=False).astype(int)
        df["RunsDescending"] = (
            df["RunsDescending"].str.replace(r"\*", "", regex=True).str.strip()
        )

        df["RunsDescending"] = pd.to_numeric(df["RunsDescending"], errors="coerce").fillna(0).astype(int)
        df["BF"] = pd.to_numeric(df["BF"], errors="coerce").fillna(0).astype(int)
        df["4s"] = pd.to_numeric(df["4s"], errors="coerce").fillna(0).astype(int)
        df["6s"] = pd.to_numeric(df["6s"], errors="coerce").fillna(0).astype(int)
        df["SR"] = df["SR"].str.strip().replace("-", "0").astype(float)
        df["Inns"] = pd.to_numeric(df["Inns"], errors="coerce").fillna(1).astype(int)
        df["Start Date"] = df["Start Date"].apply(
            lambda v: self._normalize_date(pd.to_datetime(v, errors="coerce"))
        )

        records = [
            (
                row["Player"], row["RunsDescending"], row["BF"], row["4s"], row["6s"],
                row["SR"], row["Inns"], row["Opposition"], row["Ground"],
                row["Start Date"], row["Not Out"], row["Team"],
            )
            for _, row in df.iterrows()
        ]
        inserted = self.db_manager.bulk_insert_batting(records)
        logger.info(f"Batting: {inserted} new rows inserted, {len(records) - inserted} duplicates ignored")
        return df

    # ------------------------------------------------------------------
    # Bowling
    # ------------------------------------------------------------------

    def process_bowling_data(self, scraped_data: list, columns: list[str]) -> pd.DataFrame:
        logger.info(f"Processing bowling data – {len(scraped_data)} raw rows")
        arr = self._clean_raw(scraped_data, len(columns))
        df = self._to_df(arr, columns)
        df = self._clean_opposition(df)
        df = self._split_player_team(df)

        # Remove non-bowling rows
        df = df[~df["WktsDescending"].isin(["DNB", "absent", "sub"])]
        df = df[~df["Overs"].isin(["DNB", "absent", "sub"])]

        df["Overs"] = df["Overs"].apply(self._overs_to_float)
        df["Mdns"] = df["Mdns"].replace("-", "0").astype(int)
        df["Runs"] = df["Runs"].replace("-", "0").astype(int)
        df["WktsDescending"] = df["WktsDescending"].replace("-", "0").astype(int)
        df["Econ"] = df["Econ"].replace("-", "0").astype(float)

        def safe_inns(v):
            s = str(v).split()[0]
            return int(s) if s.isdigit() else 1

        df["Inns"] = df["Inns"].apply(safe_inns)
        df["Start Date"] = df["Start Date"].apply(
            lambda v: self._normalize_date(pd.to_datetime(v, errors="coerce"))
        )

        records = [
            (
                row["Player"], row["Overs"], row["Mdns"], row["Runs"],
                row["WktsDescending"], row["Econ"], row["Inns"], row["Opposition"],
                row["Ground"], row["Start Date"], row["Team"],
            )
            for _, row in df.iterrows()
        ]
        inserted = self.db_manager.bulk_insert_bowling(records)
        logger.info(f"Bowling: {inserted} new rows inserted, {len(records) - inserted} duplicates ignored")
        return df
