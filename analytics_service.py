import hashlib
import logging
from collections import Counter

import numpy as np
import pandas as pd
import plotly.express as px
from sklearn.preprocessing import LabelEncoder

from database import DatabaseManager

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._label_encoder = LabelEncoder()
        self._match_id_cache: dict = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_match_id(self, row) -> str:
        dt = row["Start Date"]
        if isinstance(dt, str):
            dt = pd.to_datetime(dt)
        date_str = dt.strftime("%Y-%m-%d")
        key = f"{row['Ground']}_{date_str}"
        mid = hashlib.sha256(key.encode()).hexdigest()
        self._match_id_cache[mid] = (row["Ground"], row["Start Date"])
        return mid

    def _load_and_process(self):
        """Fetch from DB and return processed (df_team, df_batting, df_bowling)."""
        df_team, df_batting, df_bowling = self.db_manager.fetch_all()

        # ---- Team ----
        df_team["ScoreDescending"] = pd.to_numeric(
            df_team["ScoreDescending"], errors="coerce"
        ).astype("Int64")
        df_team["Wickets"] = df_team["Wickets"].astype("Int64")
        df_team["Start Date"] = pd.to_datetime(df_team["Start Date"])
        df_team = df_team[df_team["Start Date"] >= "1985-01-01"]

        # Host determination
        # Explicit overrides take priority over frequency-based derivation.
        # Add any ground whose host cannot be reliably inferred from match counts.
        GROUND_HOST_OVERRIDES: dict[str, str] = {
            "Guwahati": "India",
            # Add further overrides here as needed, e.g.:
            # "Multan": "Pakistan",
        }

        ground_counts: dict[str, Counter] = {}
        for _, row in df_team.iterrows():
            g = row["Ground"]
            ground_counts.setdefault(g, Counter())
            ground_counts[g].update([row["Team"], row["Opposition"]])

        def _derive_host(ground: str) -> str:
            if ground in GROUND_HOST_OVERRIDES:
                return GROUND_HOST_OVERRIDES[ground]
            if ground in ground_counts:
                return ground_counts[ground].most_common(1)[0][0]
            return ""

        df_team["Host"] = df_team["Ground"].apply(_derive_host)
        df_team["Outcome"] = df_team["Result"].map(
            {"won": "Win", "lost": "Loss", "draw": "Draw"}
        )

        # ---- Batting / Bowling ----
        def prep(df):
            if "Country" in df.columns:
                df.rename(columns={"Country": "Team"}, inplace=True)
            df["Start Date"] = pd.to_datetime(df["Start Date"])
            return df[df["Start Date"] >= "1985-01-01"]

        df_batting = prep(df_batting)
        df_bowling = prep(df_bowling)

        # Match IDs
        for df in [df_team, df_batting, df_bowling]:
            df["Match ID"] = df.apply(self._generate_match_id, axis=1)

        all_ids = pd.concat(
            [df_team["Match ID"], df_batting["Match ID"], df_bowling["Match ID"]]
        )
        self._label_encoder.fit(all_ids)

        for df in [df_team, df_batting, df_bowling]:
            df["NumericMatchID"] = self._label_encoder.transform(df["Match ID"])
            df.drop(columns=["Match ID"], inplace=True)

        # Clean junk rows
        df_batting = df_batting[
            ~((df_batting["RunsDescending"] == 0) & (df_batting["BF"] == 0))
        ]
        df_bowling = df_bowling[
            ~((df_bowling["WktsDescending"] == 0) & (df_bowling["Runs"] == 0))
        ]

        return df_team, df_batting, df_bowling

    # ------------------------------------------------------------------
    # Plots
    # ------------------------------------------------------------------

    def generate_player_batting_average_plot(self, player_name: str):
        try:
            _, df_batting, _ = self._load_and_process()
            if player_name not in df_batting["Player"].values:
                return None

            df_p = df_batting[df_batting["Player"] == player_name].copy()
            df_p["Year"] = df_p["Start Date"].dt.year
            df_p["Outs"] = 1 - df_p["Not Out"]
            df_p.sort_values("Start Date", inplace=True)

            yearly = df_p.groupby("Year", as_index=False).agg(
                Total_Runs=("RunsDescending", "sum"),
                Outs=("Outs", "sum"),
                Matches_Played=("NumericMatchID", "nunique"),
                Highest_Score=("RunsDescending", "max"),
            )
            yearly.sort_values("Year", inplace=True)

            yearly["Cumulative Runs"] = yearly["Total_Runs"].cumsum()
            yearly["Cumulative Outs"] = yearly["Outs"].cumsum()
            yearly["Cumulative Matches Played"] = yearly["Matches_Played"].cumsum()
            yearly["Cumulative Highest Score"] = yearly["Highest_Score"].cummax()
            yearly["Cumulative Batting Average"] = (
                yearly["Cumulative Runs"] / yearly["Cumulative Outs"]
            ).replace([np.inf, -np.inf], np.nan)

            import plotly.graph_objects as go, json as _json
            x_vals = yearly["Year"].tolist()
            y_vals = [round(v, 2) if not np.isnan(v) else None for v in yearly["Cumulative Batting Average"].tolist()]
            runs_vals = yearly["Cumulative Runs"].tolist()
            matches_vals = yearly["Cumulative Matches Played"].tolist()
            hs_vals = yearly["Cumulative Highest Score"].tolist()
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_vals, y=y_vals,
                mode="lines+markers",
                marker=dict(size=6),
                line=dict(width=2),
                customdata=list(zip(runs_vals, matches_vals, hs_vals)),
                hovertemplate="Year: %{x}<br>Avg: %{y:.2f}<br>Runs: %{customdata[0]}<br>Matches: %{customdata[1]}<br>Highest: %{customdata[2]}<extra></extra>",
            ))
            fig.update_layout(
                title=f"{player_name} – Cumulative Batting Average",
                hovermode="x unified", showlegend=False,
                xaxis=dict(title="Year", type="linear", dtick=1, tickangle=-45, gridcolor="rgba(255,255,255,0.06)"),
                yaxis=dict(title="Cumulative Batting Average", gridcolor="rgba(255,255,255,0.06)"),
                margin=dict(l=60, r=40, t=60, b=100),
                hoverlabel=dict(bgcolor="rgba(20,26,18,0.95)", bordercolor="rgba(94,139,61,0.6)", font=dict(color="#e8dcbb", size=12), namelength=-1),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8dcbb"),
            )
            return _json.dumps(fig.to_dict())
        except Exception as e:
            logger.error(f"generate_player_batting_average_plot: {e}")
            return None

    def generate_player_bowling_average_plot(self, player_name: str):
        try:
            _, _, df_bowling = self._load_and_process()
            if player_name not in df_bowling["Player"].values:
                return None

            df_p = df_bowling[df_bowling["Player"] == player_name].copy()
            df_p["Year"] = df_p["Start Date"].dt.year
            df_p.sort_values("Start Date", inplace=True)

            # Best figures per year: most wickets, ties broken by fewest runs
            def best_figures(g):
                best = g.sort_values(["WktsDescending", "Runs"], ascending=[False, True]).iloc[0]
                return pd.Series({
                    "Total_Runs_Conceded": g["Runs"].sum(),
                    "Total_Wickets": g["WktsDescending"].sum(),
                    "Matches_Played": g["NumericMatchID"].nunique(),
                    "Best_Wickets": best["WktsDescending"],
                    "Best_Runs": best["Runs"],
                })
            yearly = df_p.groupby("Year", as_index=False).apply(best_figures)
            yearly.sort_values("Year", inplace=True)

            yearly["Cumulative Runs Conceded"] = yearly["Total_Runs_Conceded"].cumsum()
            yearly["Cumulative Wickets"] = yearly["Total_Wickets"].cumsum()
            yearly["Cumulative Matches Played"] = yearly["Matches_Played"].cumsum()
            yearly["Cumulative Bowling Average"] = np.where(
                yearly["Cumulative Wickets"] > 0,
                yearly["Cumulative Runs Conceded"] / yearly["Cumulative Wickets"],
                np.nan,
            )

            # Cumulative best figures: carry forward the best seen so far each year
            cum_best = []
            cur_best_w = 0
            cur_best_r = float("inf")
            for _, row in yearly.iterrows():
                w, r = row["Best_Wickets"], row["Best_Runs"]
                if w > cur_best_w or (w == cur_best_w and r < cur_best_r):
                    cur_best_w, cur_best_r = w, r
                cum_best.append(f"{int(cur_best_w)}-{int(cur_best_r)}")
            yearly["Cumulative Best Figures"] = cum_best

            import plotly.graph_objects as go, json as _json
            x_vals = yearly["Year"].tolist()
            y_vals = [round(v, 2) if not np.isnan(v) else None for v in yearly["Cumulative Bowling Average"].tolist()]
            runs_vals = yearly["Cumulative Runs Conceded"].tolist()
            wkts_vals = yearly["Cumulative Wickets"].tolist()
            matches_vals = yearly["Cumulative Matches Played"].tolist()
            best_figs_vals = yearly["Cumulative Best Figures"].tolist()
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_vals, y=y_vals,
                mode="lines+markers",
                marker=dict(size=6),
                line=dict(width=2),
                customdata=list(zip(runs_vals, wkts_vals, matches_vals, best_figs_vals)),
                hovertemplate="Year: %{x}<br>Avg: %{y:.2f}<br>Runs Conceded: %{customdata[0]}<br>Wickets: %{customdata[1]}<br>Matches: %{customdata[2]}<br>Best Figures: %{customdata[3]}<extra></extra>",
            ))
            fig.update_layout(
                title=f"{player_name} – Cumulative Bowling Average",
                hovermode="x unified", showlegend=False,
                xaxis=dict(title="Year", type="linear", dtick=1, tickangle=-45, gridcolor="rgba(255,255,255,0.06)"),
                yaxis=dict(title="Cumulative Bowling Average", gridcolor="rgba(255,255,255,0.06)"),
                margin=dict(l=60, r=40, t=60, b=100),
                hoverlabel=dict(bgcolor="rgba(20,26,18,0.95)", bordercolor="rgba(94,139,61,0.6)", font=dict(color="#e8dcbb", size=12), namelength=-1),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8dcbb"),
            )
            return _json.dumps(fig.to_dict())
        except Exception as e:
            logger.error(f"generate_player_bowling_average_plot: {e}")
            return None

    # ------------------------------------------------------------------
    # Analysis endpoints  (return shapes matched to the UI)
    # ------------------------------------------------------------------

    def analyze_batsman_vs_bowler(self, batsman_name: str, bowler_name: str | None):
        """
        UI expects:
          analysis_type          "with_bowler" | "without_bowler"
          batsman / batsman_team
          bowler / bowler_team   (when bowler supplied)
          overall_average, total_runs_overall, total_outs_overall
          average_with_bowler, total_runs_with_bowler, total_outs_with_bowler
          average_without_bowler, total_runs_without_bowler, total_outs_without_bowler
          total_matches_vs_opposition, matches_with_bowler, matches_without_bowler
        """
        try:
            df_team, df_batting, df_bowling = self._load_and_process()
            player_data = df_batting[df_batting["Player"] == batsman_name]
            if player_data.empty:
                return {"error": f"No batting data for '{batsman_name}'"}

            batsman_team = player_data["Team"].mode()[0] if "Team" in player_data.columns else "Unknown"

            if not bowler_name:
                # No bowler — overall average across all innings, all teams
                total_runs_overall = int(player_data["RunsDescending"].sum())
                total_outs_overall = int((1 - player_data["Not Out"]).sum())
                overall_average = round(total_runs_overall / total_outs_overall, 2) if total_outs_overall else 0
                return {
                    "analysis_type": "without_bowler",
                    "batsman": batsman_name,
                    "batsman_team": batsman_team,
                    "bowler": None,
                    "bowler_team": None,
                    "overall_average": overall_average,
                    "total_runs_overall": total_runs_overall,
                    "total_outs_overall": total_outs_overall,
                    "total_matches_vs_opposition": player_data["NumericMatchID"].nunique(),
                    "average_with_bowler": None,
                    "total_runs_with_bowler": None,
                    "total_outs_with_bowler": None,
                    "average_without_bowler": None,
                    "total_runs_without_bowler": None,
                    "total_outs_without_bowler": None,
                    "matches_with_bowler": None,
                    "matches_without_bowler": None,
                }

            # --- bowler supplied ---
            bowler_data = df_bowling[df_bowling["Player"] == bowler_name]
            if bowler_data.empty:
                return {"error": f"No bowling data for '{bowler_name}'"}

            bowler_team = bowler_data["Team"].mode()[0] if "Team" in bowler_data.columns else "Unknown"
            bowler_match_ids = set(bowler_data["NumericMatchID"].unique())

            # Overall average = vs the bowler's team only (matches original logic)
            vs_opposition = player_data[player_data["Opposition"] == bowler_team]
            if vs_opposition.empty:
                vs_opposition = player_data   # fallback: all data if no head-to-head found

            total_runs_overall = int(vs_opposition["RunsDescending"].sum())
            total_outs_overall = int((1 - vs_opposition["Not Out"]).sum())
            overall_average = round(total_runs_overall / total_outs_overall, 2) if total_outs_overall else 0

            # Split: matches where bowler played vs not
            with_bowler    = vs_opposition[vs_opposition["NumericMatchID"].isin(bowler_match_ids)]
            without_bowler = vs_opposition[~vs_opposition["NumericMatchID"].isin(bowler_match_ids)]

            def _avg(df):
                runs = int(df["RunsDescending"].sum())
                outs = int((1 - df["Not Out"]).sum())
                avg  = round(runs / outs, 2) if outs else 0
                return runs, outs, avg

            runs_with,    outs_with,    avg_with    = _avg(with_bowler)
            runs_without, outs_without, avg_without = _avg(without_bowler)

            return {
                "analysis_type": "with_bowler",
                "batsman": batsman_name,
                "batsman_team": batsman_team,
                "bowler": bowler_name,
                "bowler_team": bowler_team,
                "overall_average": overall_average,
                "total_runs_overall": total_runs_overall,
                "total_outs_overall": total_outs_overall,
                "total_matches_vs_opposition": vs_opposition["NumericMatchID"].nunique(),
                "matches_with_bowler":    with_bowler["NumericMatchID"].nunique(),
                "matches_without_bowler": without_bowler["NumericMatchID"].nunique(),
                "average_with_bowler":    avg_with,
                "total_runs_with_bowler": runs_with,
                "total_outs_with_bowler": outs_with,
                "average_without_bowler":    avg_without,
                "total_runs_without_bowler": runs_without,
                "total_outs_without_bowler": outs_without,
            }
        except Exception as e:
            logger.error(f"analyze_batsman_vs_bowler: {e}")
            return None

    def analyze_batting_match_outcomes(self, player_name: str, min_score: int):
        """
        UI expects: player, team, min_score, qualifying_innings,
                    total_matches, matches_won, matches_lost, matches_drawn,
                    winning_percentage, losing_percentage, drawing_percentage
        """
        try:
            df_team, df_batting, _ = self._load_and_process()
            player_data = df_batting[df_batting["Player"] == player_name]
            if player_data.empty:
                return {"error": f"No data for '{player_name}'"}

            player_team = player_data["Team"].mode()[0]
            qualifying = player_data[player_data["RunsDescending"] >= min_score]

            if qualifying.empty:
                return {"error": f"'{player_name}' never scored ≥{min_score}"}

            match_ids = qualifying["NumericMatchID"].unique()
            # Filter df_team to the player's team in those matches,
            # then count by unique match (not innings rows — a match has 2 innings rows)
            team_matches = df_team[
                (df_team["Team"] == player_team) &
                (df_team["NumericMatchID"].isin(match_ids))
            ]
            # Use nunique on NumericMatchID grouped by Result to match original logic
            won  = team_matches[team_matches["Result"] == "won"]["NumericMatchID"].nunique()
            lost = team_matches[team_matches["Result"] == "lost"]["NumericMatchID"].nunique()
            drawn = team_matches[team_matches["Result"] == "draw"]["NumericMatchID"].nunique()
            total = len(match_ids)  # unique qualifying matches, exactly as original

            return {
                "player": player_name,
                "team": player_team,
                "min_score": min_score,
                "qualifying_innings": len(qualifying),
                "total_matches": total,
                "matches_won": won,
                "matches_lost": lost,
                "matches_drawn": drawn,
                "winning_percentage": round(won / total * 100, 2) if total else 0,
                "losing_percentage": round(lost / total * 100, 2) if total else 0,
                "drawing_percentage": round(drawn / total * 100, 2) if total else 0,
            }
        except Exception as e:
            logger.error(f"analyze_batting_match_outcomes: {e}")
            return None

    def analyze_bowling_match_outcomes(self, player_name: str, min_wickets: int):
        """
        UI expects: player, team, min_wickets, qualifying_innings,
                    total_matches, matches_won, matches_lost, matches_drawn,
                    winning_percentage, losing_percentage, drawing_percentage
        """
        try:
            df_team, _, df_bowling = self._load_and_process()
            player_data = df_bowling[df_bowling["Player"] == player_name]
            if player_data.empty:
                return {"error": f"No data for '{player_name}'"}

            player_team = player_data["Team"].mode()[0]
            qualifying = player_data[player_data["WktsDescending"] >= min_wickets]

            if qualifying.empty:
                return {"error": f"'{player_name}' never took ≥{min_wickets} wickets"}

            match_ids = qualifying["NumericMatchID"].unique()
            team_matches = df_team[
                (df_team["Team"] == player_team) &
                (df_team["NumericMatchID"].isin(match_ids))
            ]
            won   = team_matches[team_matches["Result"] == "won"]["NumericMatchID"].nunique()
            lost  = team_matches[team_matches["Result"] == "lost"]["NumericMatchID"].nunique()
            drawn = team_matches[team_matches["Result"] == "draw"]["NumericMatchID"].nunique()
            total = len(match_ids)  # unique qualifying matches

            return {
                "player": player_name,
                "team": player_team,
                "min_wickets": min_wickets,
                "qualifying_innings": len(qualifying),
                "total_matches": total,
                "matches_won": won,
                "matches_lost": lost,
                "matches_drawn": drawn,
                "winning_percentage": round(won / total * 100, 2) if total else 0,
                "losing_percentage": round(lost / total * 100, 2) if total else 0,
                "drawing_percentage": round(drawn / total * 100, 2) if total else 0,
            }
        except Exception as e:
            logger.error(f"analyze_bowling_match_outcomes: {e}")
            return None

    def analyze_batting_by_country(self, player_name: str):
        """
        UI expects: player, player_team, total_countries,
                    country_statistics: [{country, matches_played, batting_average,
                                          total_runs, times_out}]
                    sorted by batting_average descending
        """
        try:
            df_team, df_batting, _ = self._load_and_process()
            player_data = df_batting[df_batting["Player"] == player_name]
            if player_data.empty:
                return {"error": f"No batting data for '{player_name}'"}

            player_team = player_data["Team"].mode()[0] if "Team" in player_data.columns else "Unknown"

            merged = player_data.merge(
                df_team[["NumericMatchID", "Host"]].drop_duplicates(),
                on="NumericMatchID", how="left",
            )
            stats = []
            for country, grp in merged.groupby("Host"):
                runs = int(grp["RunsDescending"].sum())
                outs = int((1 - grp["Not Out"]).sum())
                avg = round(runs / outs, 2) if outs else 0
                stats.append({
                    "country": country,
                    "matches_played": grp["NumericMatchID"].nunique(),
                    "batting_average": avg,
                    "total_runs": runs,
                    "times_out": outs,
                    "highest_score": int(grp["RunsDescending"].max()),
                })

            # Sort by batting average descending (best country first)
            stats.sort(key=lambda x: x["batting_average"], reverse=True)

            return {
                "player": player_name,
                "player_team": player_team,
                "total_countries": len(stats),
                "country_statistics": stats,
            }
        except Exception as e:
            logger.error(f"analyze_batting_by_country: {e}")
            return None

    def analyze_bowling_by_country(self, player_name: str):
        """
        UI expects: player, player_team, total_countries,
                    country_statistics: [{country, matches_played, bowling_average,
                                          total_runs_conceded, total_wickets}]
                    sorted by bowling_average ascending (lower = better)
        """
        try:
            df_team, _, df_bowling = self._load_and_process()
            player_data = df_bowling[df_bowling["Player"] == player_name]
            if player_data.empty:
                return {"error": f"No bowling data for '{player_name}'"}

            player_team = player_data["Team"].mode()[0] if "Team" in player_data.columns else "Unknown"

            merged = player_data.merge(
                df_team[["NumericMatchID", "Host"]].drop_duplicates(),
                on="NumericMatchID", how="left",
            )
            stats = []
            for country, grp in merged.groupby("Host"):
                runs = int(grp["Runs"].sum())
                wkts = int(grp["WktsDescending"].sum())
                avg = round(runs / wkts, 2) if wkts else None
                stats.append({
                    "country": country,
                    "matches_played": grp["NumericMatchID"].nunique(),
                    "bowling_average": avg,
                    "total_runs_conceded": runs,
                    "total_wickets": wkts,
                    "economy": round(float(grp["Econ"].mean()), 2),
                })

            # Sort by bowling average ascending (best = lowest avg first);
            # push None (0 wickets) to the end
            stats.sort(key=lambda x: (x["bowling_average"] is None, x["bowling_average"] or 9999))

            return {
                "player": player_name,
                "player_team": player_team,
                "total_countries": len(stats),
                "country_statistics": stats,
            }
        except Exception as e:
            logger.error(f"analyze_bowling_by_country: {e}")
            return None

    def generate_batting_comparison_plot(self, player1: str, player2: str):
        """
        Yearly batting average for two players on one chart.
        Hover shows: total runs, matches played, highest score for that year.
        """
        try:
            import plotly.graph_objects as go, json as _json

            _, df_batting, _ = self._load_and_process()

            players = [p for p in [player1, player2]
                       if p in df_batting["Player"].values]
            if not players:
                return None

            fig = go.Figure()
            colours = ["#10b981", "#f59e0b"]

            for colour, player in zip(colours, players):
                df_p = df_batting[df_batting["Player"] == player].copy()
                df_p["Year"] = df_p["Start Date"].dt.year

                yearly = df_p.groupby("Year", as_index=False).apply(
                    lambda g: pd.Series({
                        "Batting Average": (
                            g["RunsDescending"].sum() / (1 - g["Not Out"]).sum()
                            if (1 - g["Not Out"]).sum() > 0 else 0
                        ),
                        "Total Runs":     int(g["RunsDescending"].sum()),
                        "Matches Played": g["NumericMatchID"].nunique(),
                        "Highest Score":  int(g["RunsDescending"].max()),
                    })
                ).sort_values("Year")

                fig.add_trace(go.Scatter(
                    x=yearly["Year"].tolist(),
                    y=[round(v, 2) for v in yearly["Batting Average"].tolist()],
                    name=player,
                    mode="lines+markers",
                    line=dict(width=2, color=colour),
                    marker=dict(size=6, color=colour),
                    customdata=list(zip(
                        yearly["Total Runs"].tolist(),
                        yearly["Matches Played"].tolist(),
                        yearly["Highest Score"].tolist(),
                    )),
                    hovertemplate=(
                        f"<b>{player}</b><br>"
                        "Year: %{x}<br>"
                        "Average: %{y:.2f}<br>"
                        "Runs: %{customdata[0]}<br>"
                        "Matches: %{customdata[1]}<br>"
                        "Highest: %{customdata[2]}"
                        "<extra></extra>"
                    ),
                ))

            fig.update_layout(
                title=f"{player1} vs {player2} — Batting Average by Year",
                xaxis=dict(title="Year", type="linear", dtick=1, tickangle=-45, gridcolor="rgba(255,255,255,0.06)"),
                yaxis=dict(title="Batting Average", gridcolor="rgba(255,255,255,0.06)"),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=60, r=40, t=60, b=100),
                hoverlabel=dict(bgcolor="rgba(20,26,18,0.95)", bordercolor="rgba(94,139,61,0.6)", font=dict(color="#e8dcbb", size=12), namelength=-1),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8dcbb"),
            )
            return _json.dumps(fig.to_dict())
        except Exception as e:
            logger.error(f"generate_batting_comparison_plot: {e}")
            return None

    def generate_bowling_comparison_plot(self, player1: str, player2: str):
        """
        Yearly bowling average for two players on one chart.
        Hover shows: total wickets, matches played, best figures for that year.
        """
        try:
            import plotly.graph_objects as go, json as _json

            _, _, df_bowling = self._load_and_process()

            players = [p for p in [player1, player2]
                       if p in df_bowling["Player"].values]
            if not players:
                return None

            fig = go.Figure()
            colours = ["#3b82f6", "#ef4444"]

            for colour, player in zip(colours, players):
                df_p = df_bowling[df_bowling["Player"] == player].copy()
                df_p["Year"] = df_p["Start Date"].dt.year

                def yearly_bowling(g):
                    best = g.sort_values(
                        ["WktsDescending", "Runs"], ascending=[False, True]
                    ).iloc[0]
                    wkts = g["WktsDescending"].sum()
                    return pd.Series({
                        "Bowling Average": (
                            g["Runs"].sum() / wkts if wkts > 0 else None
                        ),
                        "Total Wickets":   int(wkts),
                        "Matches Played":  g["NumericMatchID"].nunique(),
                        "Best Figures":    f"{int(best['WktsDescending'])}-{int(best['Runs'])}",
                    })

                yearly = df_p.groupby("Year", as_index=False).apply(
                    yearly_bowling
                ).sort_values("Year")

                # Drop years with 0 wickets (no average to plot)
                yearly = yearly[yearly["Bowling Average"].notna()]

                fig.add_trace(go.Scatter(
                    x=yearly["Year"].tolist(),
                    y=[round(v, 2) for v in yearly["Bowling Average"].tolist()],
                    name=player,
                    mode="lines+markers",
                    line=dict(width=2, color=colour),
                    marker=dict(size=6, color=colour),
                    customdata=list(zip(
                        yearly["Total Wickets"].tolist(),
                        yearly["Matches Played"].tolist(),
                        yearly["Best Figures"].tolist(),
                    )),
                    hovertemplate=(
                        f"<b>{player}</b><br>"
                        "Year: %{x}<br>"
                        "Average: %{y:.2f}<br>"
                        "Wickets: %{customdata[0]}<br>"
                        "Matches: %{customdata[1]}<br>"
                        "Best: %{customdata[2]}"
                        "<extra></extra>"
                    ),
                ))

            fig.update_layout(
                title=f"{player1} vs {player2} — Bowling Average by Year",
                xaxis=dict(title="Year", type="linear", dtick=1, tickangle=-45, gridcolor="rgba(255,255,255,0.06)"),
                yaxis=dict(title="Bowling Average (lower = better)", gridcolor="rgba(255,255,255,0.06)"),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=60, r=40, t=60, b=100),
                hoverlabel=dict(bgcolor="rgba(20,26,18,0.95)", bordercolor="rgba(94,139,61,0.6)", font=dict(color="#e8dcbb", size=12), namelength=-1),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8dcbb"),
            )
            return _json.dumps(fig.to_dict())
        except Exception as e:
            logger.error(f"generate_bowling_comparison_plot: {e}")
            return None

    def generate_team_batting_average_plot(self):
        """
        Bar chart of batting average for every team, sorted highest first.
        Average = (11 * total_runs) / total_outs, matching your original formula.
        """
        try:
            import plotly.graph_objects as go, json as _json

            _, df_batting, _ = self._load_and_process()

            agg = df_batting.groupby("Team").apply(
                lambda g: pd.Series({
                    "Total Runs": g["RunsDescending"].sum(),
                    "Total Outs": (g["Not Out"] == 0).sum(),
                })
            ).reset_index()

            agg = agg[agg["Total Outs"] > 0].copy()
            agg["Batting Average"] = (11 * agg["Total Runs"] / agg["Total Outs"]).round(2)
            agg.sort_values("Batting Average", ascending=False, inplace=True)

            fig = go.Figure(go.Bar(
                x=agg["Team"].tolist(),
                y=agg["Batting Average"].tolist(),
                marker_color="#10b981",
                customdata=list(zip(
                    agg["Total Runs"].tolist(),
                    agg["Total Outs"].tolist(),
                )),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Batting Average: %{y:.2f}<br>"
                    "Total Runs: %{customdata[0]}<br>"
                    "Total Outs: %{customdata[1]}"
                    "<extra></extra>"
                ),
            ))
            fig.update_layout(
                title="Team Batting Averages — All Time",
                xaxis=dict(title="Team", tickangle=-30, gridcolor="rgba(255,255,255,0.06)"),
                yaxis=dict(title="Batting Average", gridcolor="rgba(255,255,255,0.06)"),
                margin=dict(l=60, r=40, t=60, b=120),
                hoverlabel=dict(bgcolor="rgba(20,26,18,0.95)", bordercolor="rgba(94,139,61,0.6)", font=dict(color="#e8dcbb", size=12), namelength=-1),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8dcbb"),
            )
            return _json.dumps(fig.to_dict())
        except Exception as e:
            logger.error(f"generate_team_batting_average_plot: {e}")
            return None

