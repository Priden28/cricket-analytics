"""
predictor_service.py
--------------------
Importable wrapper around the trained CricketMatchPredictor.

The API imports this module at startup.  Training is done offline via
ML_First.py; this module only loads the saved .pkl and serves predictions.

Exposed:
  PredictorService.from_pkl(path)   – load from saved model file
  PredictorService.teams            – sorted list of known team names
  PredictorService.players_by_team  – dict {team: [player, ...]}
  PredictorService.predict(...)     – run a match prediction
  PredictorService.model_info()     – accuracy / feature importance metadata
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import joblib
import pandas as pd

logger = logging.getLogger(__name__)


class PredictorService:
    """
    Thin wrapper around CricketMatchPredictor that:
      - loads the trained model + data from disk once at startup
      - pre-builds the team→player index from the batting + bowling tables
      - exposes a clean predict() method for the API layer
      - is thread-safe (read-only after init)
    """

    def __init__(self, predictor, accuracy: float = 0.0,
                 feature_importance: Optional[pd.DataFrame] = None):
        self._predictor        = predictor
        self._accuracy         = accuracy
        self._feature_importance = feature_importance
        self._lock             = threading.Lock()   # future-proof for retraining

        # Build team → sorted player list from batting + bowling tables
        self._teams, self._players_by_team = self._build_player_index()

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_pkl(cls, pkl_path: str = "cricket_match_predictor.pkl") -> "PredictorService":
        """
        Load a previously trained model saved by ML_First.py.

        The pkl must have been produced by ML_First.py which also pickles
        df_batting and df_bowling on the predictor so we can rebuild the
        player index without hitting the DB again.

        If df_batting / df_bowling are NOT in the pkl (older saves), we fall
        back to re-loading from the DB via the predictor's own load method.
        """
        path = Path(pkl_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Model file not found: {pkl_path}\n"
                "Run ML_First.py first to train and save the model."
            )

        logger.info(f"Loading model from {pkl_path} ...")
        saved = joblib.load(pkl_path)

        # ML_First.py saves a dict with model + metadata
        if isinstance(saved, dict):
            from ML_First import CricketMatchPredictor  # noqa: PLC0415
            predictor                      = CricketMatchPredictor()
            predictor.model                = saved["model"]
            predictor.label_encoder        = saved["label_encoder"]
            predictor.match_id_label_encoder = saved["match_id_label_encoder"]
            predictor.feature_columns      = saved["feature_columns"]
            predictor.match_id_dict        = saved.get("match_id_dict", {})
            accuracy                       = saved.get("accuracy", 0.0)
            feature_importance             = saved.get("feature_importance", None)

            # Data frames — needed for player index + stat lookups
            if "df_batting" in saved and "df_bowling" in saved and "df_team" in saved:
                predictor.df_batting = saved["df_batting"]
                predictor.df_bowling = saved["df_bowling"]
                predictor.df_team    = saved["df_team"]
                logger.info("Data frames loaded from pkl.")
            else:
                logger.warning("pkl has no data frames — loading from DB ...")
                predictor.load_data_from_db()
        else:
            # Legacy: the predictor object itself was pickled directly
            predictor          = saved
            accuracy           = 0.0
            feature_importance = None
            if not hasattr(predictor, "df_batting"):
                predictor.load_data_from_db()

        logger.info("Model loaded successfully.")
        return cls(predictor, accuracy, feature_importance)

    # ── Player index ──────────────────────────────────────────────────────────

    def _build_player_index(self) -> tuple[list[str], dict[str, list[str]]]:
        """
        Build {team: [player, ...]} from the batting and bowling dataframes.
        A player appears under a team if they batted OR bowled for that team.
        Players with no DB records at all are excluded.
        """
        p = self._predictor
        bat = p.df_batting[["Player", "Team"]].copy()
        bowl = p.df_bowling[["Player", "Team"]].copy()
        combined = pd.concat([bat, bowl]).drop_duplicates()

        players_by_team: dict[str, list[str]] = {}
        for team, grp in combined.groupby("Team"):
            players_by_team[str(team)] = sorted(grp["Player"].unique().tolist())

        teams = sorted(players_by_team.keys())
        total = sum(len(v) for v in players_by_team.values())
        logger.info(f"Player index built: {len(teams)} teams, {total} player-team entries")
        return teams, players_by_team

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def teams(self) -> list[str]:
        return self._teams

    @property
    def players_by_team(self) -> dict[str, list[str]]:
        return self._players_by_team

    def players_for_team(self, team: str) -> list[str]:
        return self._players_by_team.get(team, [])

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(
        self,
        team: str,
        team_players: list[str],
        opposition: str,
        opp_players: list[str],
        venue_type: str = "neutral",          # 'home' | 'away' | 'neutral'
        match_date: Optional[datetime] = None,
    ) -> dict:
        """
        Run a match prediction and return a JSON-serialisable result dict.

        The result dict shape matches what the UI expects:
          team, opposition, venue_type,
          predicted_outcome ('Win' | 'Loss'),
          win_probability (0–1), loss_probability (0–1),
          predicted_winner,
          factors: [{name, team_value, opp_value, advantage, description}, ...]
          warnings: [{team, message}, ...]
        """
        if len(team_players) != 11:
            raise ValueError(f"team_players must have exactly 11 entries, got {len(team_players)}")
        if len(opp_players) != 11:
            raise ValueError(f"opp_players must have exactly 11 entries, got {len(opp_players)}")
        if venue_type not in ("home", "away", "neutral"):
            raise ValueError(f"venue_type must be 'home', 'away', or 'neutral'")

        with self._lock:
            raw = self._predictor.predict(
                team=team,
                team_players=team_players,
                opposition=opposition,
                opp_players=opp_players,
                venue_type=venue_type,
                match_date=match_date,
            )

        # Extract data-quality warnings into a flat list for the UI
        tf  = raw["team_features"]
        of_ = raw["opposition_features"]
        warnings = []
        for label, feat in ((team, tf), (opposition, of_)):
            nb = feat.get("_num_batters", 0)
            nw = feat.get("_num_bowlers", 0)
            thin_b = feat.get("_thin_batters", [])
            thin_w = feat.get("_thin_bowlers", [])
            if nb < 7:
                warnings.append({"team": label,
                                  "message": f"Only {nb} players with batting records — averages may be understated"})
            if nw < 5:
                warnings.append({"team": label,
                                  "message": f"Only {nw} players with bowling records"})
            if thin_b:
                warnings.append({"team": label,
                                  "message": f"Thin batting data (<10 innings): {', '.join(thin_b)}"})
            if thin_w:
                warnings.append({"team": label,
                                  "message": f"Thin bowling data (<10 matches): {', '.join(thin_w)}"})

        return {
            "team":               raw["team"],
            "opposition":         raw["opposition"],
            "venue_type":         raw["venue_type"],
            "predicted_outcome":  raw["predicted_outcome"],
            "predicted_winner":   team if raw["predicted_outcome"] == "Win" else opposition,
            "win_probability":    round(raw["win_probability"], 4),
            "loss_probability":   round(raw["loss_probability"], 4),
            "factors":            raw["factors"],
            "warnings":           warnings,
        }

    # ── Model metadata ────────────────────────────────────────────────────────

    def model_info(self) -> dict:
        fi = []
        if self._feature_importance is not None:
            fi = self._feature_importance.head(15).to_dict(orient="records")
        return {
            "accuracy":            round(self._accuracy, 4),
            "feature_importance":  fi,
            "model_loaded":        True,
        }
