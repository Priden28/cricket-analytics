import pandas as pd
import numpy as np
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.preprocessing import LabelEncoder
import joblib
import logging
from datetime import datetime, timedelta
import hashlib
from collections import Counter
import warnings
import psycopg2

warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATABASE CONFIGURATION
# ─────────────────────────────────────────────
DB_CONFIG = {
    'host': 'localhost',
    'dbname': 'Cricket',
    'user': 'postgres',
    'password': 'B@rnat028',
    'port': 5432,
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def test_connection():
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT version();")
        logger.info(f"Connected: {cur.fetchone()[0]}")
        for tbl in ('team', 'batting', 'bowling'):
            cur.execute(f"SELECT COUNT(*) FROM {tbl};")
            logger.info(f"   {tbl}: {cur.fetchone()[0]:,} rows")
        cur.close(); conn.close()
        return True
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PREDICTOR
# ─────────────────────────────────────────────────────────────────────────────
class CricketMatchPredictor:
    """
    XGBoost model that predicts match outcomes from a Playing XI + venue.

    Key fix vs. previous version
    -----------------------------
    prepare_training_data() now adds BOTH perspectives of every match
    (team-A-as-primary AND team-B-as-primary), guaranteeing a 50/50
    win/loss split and eliminating the 87% win-rate imbalance.
    """

    def __init__(self):
        self.model = XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            eval_metric='logloss',
            use_label_encoder=False,
        )
        self.label_encoder           = LabelEncoder()
        self.match_id_label_encoder  = LabelEncoder()
        self.feature_columns         = []
        self.match_id_dict           = {}

    # ── Match-ID ──────────────────────────────────────────────────────────────

    def generate_match_id(self, row):
        start = row['Start Date']
        if isinstance(start, str):
            start = pd.to_datetime(start)
        key      = f"{row['Ground']}_{start.strftime('%Y-%m-%d')}"
        match_id = hashlib.sha256(key.encode()).hexdigest()
        self.match_id_dict[match_id] = (row['Ground'], row['Start Date'])
        return match_id

    # ── Loading ───────────────────────────────────────────────────────────────

    def load_data_from_db(self):
        logger.info("Loading data from PostgreSQL ...")
        conn = get_connection()
        try:
            self.df_team    = pd.read_sql("SELECT * FROM team",    conn)
            self.df_batting = pd.read_sql("SELECT * FROM batting",  conn)
            self.df_bowling = pd.read_sql("SELECT * FROM bowling",  conn)
        finally:
            conn.close()

        logger.info(f"Loaded {len(self.df_team):,} team records")
        logger.info(f"Loaded {len(self.df_batting):,} batting records")
        logger.info(f"Loaded {len(self.df_bowling):,} bowling records")

        self._normalise_columns()
        self._process_data()

    def _normalise_columns(self):
        """Map lowercase Postgres column names back to Title-Case expected by code."""
        team_map = {
            'start date':'Start Date','ground':'Ground','team':'Team',
            'opposition':'Opposition','scoredescending':'ScoreDescending',
            'wickets':'Wickets','result':'Result','host':'Host',
        }
        bat_map = {
            'start date':'Start Date','ground':'Ground','player':'Player',
            'team':'Team','country':'Team','runsdescending':'RunsDescending',
            'bf':'BF','not out':'Not Out','notout':'Not Out',
        }
        bowl_map = {
            'start date':'Start Date','ground':'Ground','player':'Player',
            'team':'Team','country':'Team','wktsdescending':'WktsDescending',
            'runs':'Runs','overs':'Overs','econ':'Econ',
        }

        def _apply(df, m):
            lc = {c.lower(): c for c in df.columns}
            return df.rename(columns={lc[s]: d for s, d in m.items() if s in lc and lc[s] != d})

        self.df_team    = _apply(self.df_team,    team_map)
        self.df_batting = _apply(self.df_batting, bat_map)
        self.df_bowling = _apply(self.df_bowling, bowl_map)

    def _process_data(self):
        logger.info("Processing data ...")

        # Team
        self.df_team['ScoreDescending'] = (
            pd.to_numeric(self.df_team['ScoreDescending'], errors='coerce').astype('Int64'))
        self.df_team['Wickets']    = self.df_team['Wickets'].astype('Int64')
        self.df_team['Start Date'] = pd.to_datetime(self.df_team['Start Date'])

        # Derive Host from ground frequency, with explicit overrides for grounds
        # whose host cannot be reliably inferred from match counts alone.
        GROUND_HOST_OVERRIDES: dict[str, str] = {
            'Guwahati': 'India',
            # Add further overrides here as needed, e.g.:
            # 'Multan': 'Pakistan',
        }

        gc = {}
        for _, r in self.df_team.iterrows():
            gc.setdefault(r['Ground'], Counter())
            gc[r['Ground']] += Counter([r['Team'], r['Opposition']])

        def _derive_host(ground: str) -> str:
            if ground in GROUND_HOST_OVERRIDES:
                return GROUND_HOST_OVERRIDES[ground]
            if ground in gc:
                return gc[ground].most_common(1)[0][0]
            return ''

        self.df_team['Host'] = self.df_team['Ground'].apply(_derive_host)

        self.df_team = self.df_team[self.df_team['Start Date'] >= '1985-01-01']

        # Batting
        if 'Country' in self.df_batting.columns:
            self.df_batting.rename(columns={'Country': 'Team'}, inplace=True)
        self.df_batting['Start Date'] = pd.to_datetime(self.df_batting['Start Date'])
        self.df_batting = self.df_batting[self.df_batting['Start Date'] >= '1985-01-01']

        # Bowling
        if 'Country' in self.df_bowling.columns:
            self.df_bowling.rename(columns={'Country': 'Team'}, inplace=True)
        self.df_bowling['Start Date'] = pd.to_datetime(self.df_bowling['Start Date'])
        self.df_bowling = self.df_bowling[self.df_bowling['Start Date'] >= '1985-01-01']

        # Match IDs
        logger.info("Generating Match IDs ...")
        for df in (self.df_team, self.df_batting, self.df_bowling):
            df['Match ID'] = df.apply(self.generate_match_id, axis=1)

        all_ids = pd.concat([d['Match ID'] for d in (self.df_team, self.df_batting, self.df_bowling)])
        self.match_id_label_encoder.fit(all_ids)
        for df in (self.df_team, self.df_batting, self.df_bowling):
            df['NumericMatchID'] = self.match_id_label_encoder.transform(df['Match ID'])
            df.drop('Match ID', axis=1, inplace=True)

        # Clean
        self.df_batting.drop(
            self.df_batting[(self.df_batting['RunsDescending'] == 0) &
                            (self.df_batting['BF'] == 0)].index, inplace=True)
        self.df_bowling.drop(
            self.df_bowling[(self.df_bowling['WktsDescending'] == 0) &
                            (self.df_bowling['Runs'] == 0)].index, inplace=True)

        self.df_team['Outcome'] = self.df_team['Result'].map(
            {'won': 'Win', 'lost': 'Loss', 'draw': 'Draw'})
        logger.info(f"Before filtering draws: {len(self.df_team)} records")
        self.df_team = self.df_team[self.df_team['Result'] != 'draw']
        logger.info(f"After filtering draws:  {len(self.df_team)} records")

        logger.info(f"After processing:")
        logger.info(f"  - Team records:    {len(self.df_team)}")
        logger.info(f"  - Batting records: {len(self.df_batting)}")
        logger.info(f"  - Bowling records: {len(self.df_bowling)}")
        logger.info(f"  - Unique matches:  {self.df_team['NumericMatchID'].nunique()}")

    # ── Player / team stat helpers ─────────────────────────────────────────────

    def get_match_players(self, match_id, team):
        bat = self.df_batting[
            (self.df_batting['NumericMatchID'] == match_id) &
            (self.df_batting['Team'] == team)]['Player'].unique()
        bowl = self.df_bowling[
            (self.df_bowling['NumericMatchID'] == match_id) &
            (self.df_bowling['Team'] == team)]['Player'].unique()
        return list(set(list(bat) + list(bowl)))

    def calculate_player_batting_stats(self, player, team, before_date=None,
                                       host=None, include_recent=False):
        # Primary lookup: player + team exact match
        data = self.df_batting[
            (self.df_batting['Player'] == player) &
            (self.df_batting['Team']   == team)]
        # Fallback: player name only (handles team-string mismatches between tables)
        if data.empty:
            data = self.df_batting[self.df_batting['Player'] == player]
        if before_date is not None:
            data = data[data['Start Date'] < before_date]
        if data.empty:
            base = {'batting_avg': 0, 'batting_sr': 0, 'matches_played': 0, 'total_runs': 0}
            if host:           base.update(batting_avg_location=0, batting_sr_location=0)
            if include_recent: base.update(batting_avg_recent=0,   batting_sr_recent=0)
            return base

        tr  = data['RunsDescending'].sum()
        to_ = (1 - data['Not Out']).sum()
        tb  = data['BF'].sum()
        avg = tr / to_ if to_ > 0 else 0
        sr  = (tr / tb * 100) if tb > 0 else 0

        stats = {'batting_avg': avg, 'batting_sr': sr,
                 'matches_played': data['NumericMatchID'].nunique(), 'total_runs': tr}

        if host:
            hmids = self.df_team[self.df_team['Host'] == host]['NumericMatchID'].unique()
            loc   = data[data['NumericMatchID'].isin(hmids)]
            if not loc.empty:
                lr, lo, lb = loc['RunsDescending'].sum(), (1-loc['Not Out']).sum(), loc['BF'].sum()
                stats['batting_avg_location'] = lr/lo if lo > 0 else 0
                stats['batting_sr_location']  = (lr/lb*100) if lb > 0 else 0
            else:
                stats['batting_avg_location'] = avg
                stats['batting_sr_location']  = sr

        if include_recent and before_date is not None:
            rec = data[data['Start Date'] >= before_date - timedelta(days=365)]
            if not rec.empty:
                rr, ro, rb = rec['RunsDescending'].sum(), (1-rec['Not Out']).sum(), rec['BF'].sum()
                stats['batting_avg_recent'] = rr/ro if ro > 0 else avg
                stats['batting_sr_recent']  = (rr/rb*100) if rb > 0 else sr
            else:
                stats['batting_avg_recent'] = avg
                stats['batting_sr_recent']  = sr

        return stats

    def calculate_player_bowling_stats(self, player, team, before_date=None,
                                       host=None, include_recent=False):
        # Primary lookup: player + team exact match
        data = self.df_bowling[
            (self.df_bowling['Player'] == player) &
            (self.df_bowling['Team']   == team)]
        # Fallback: player name only (handles team-string mismatches between tables)
        if data.empty:
            data = self.df_bowling[self.df_bowling['Player'] == player]
        if before_date is not None:
            data = data[data['Start Date'] < before_date]
        if data.empty:
            base = {'bowling_avg': 50, 'bowling_sr': 80, 'economy': 4.0,
                    'total_wickets': 0, 'matches_played': 0}
            if host:           base.update(bowling_avg_location=50, bowling_sr_location=80, economy_location=4.0)
            if include_recent: base.update(bowling_avg_recent=50,   bowling_sr_recent=80,   economy_recent=4.0)
            return base

        tr  = data['Runs'].sum()
        tw  = data['WktsDescending'].sum()
        tb  = data['Overs'].sum() * 6
        avg = tr / tw if tw > 0 else 50
        sr  = tb / tw if tw > 0 else 80
        eco = data['Econ'].mean()

        stats = {'bowling_avg': avg, 'bowling_sr': sr, 'economy': eco,
                 'total_wickets': tw, 'matches_played': data['NumericMatchID'].nunique()}

        if host:
            hmids = self.df_team[self.df_team['Host'] == host]['NumericMatchID'].unique()
            loc   = data[data['NumericMatchID'].isin(hmids)]
            if not loc.empty:
                lw = loc['WktsDescending'].sum()
                lb = loc['Overs'].sum() * 6
                stats['bowling_avg_location'] = loc['Runs'].sum()/lw if lw > 0 else avg
                stats['bowling_sr_location']  = lb/lw if lw > 0 else sr
                stats['economy_location']     = loc['Econ'].mean()
            else:
                stats['bowling_avg_location'] = avg
                stats['bowling_sr_location']  = sr
                stats['economy_location']     = eco

        if include_recent and before_date is not None:
            rec = data[data['Start Date'] >= before_date - timedelta(days=365)]
            if not rec.empty:
                rw = rec['WktsDescending'].sum()
                rb = rec['Overs'].sum() * 6
                stats['bowling_avg_recent'] = rec['Runs'].sum()/rw if rw > 0 else avg
                stats['bowling_sr_recent']  = rb/rw if rw > 0 else sr
                stats['economy_recent']     = rec['Econ'].mean()
            else:
                stats['bowling_avg_recent'] = avg
                stats['bowling_sr_recent']  = sr
                stats['economy_recent']     = eco

        return stats

    def calculate_team_features(self, team, players, match_date, host, opposition):
        """
        Return a feature dict for one team's XI at a given point in time.

        DNB fix
        -------
        Players who did not bat (DNB) are absent from the batting table, so they
        return batting_avg=0 and total_runs=0.  Including them in the batting
        average mean would dilute the figure by a false denominator.

        Rule: only players who actually have batting records (total_runs > 0 OR
        matches_played > 0) are included in batting average lists.  Bowling lists
        still include all players — a specialist batter who never bowled should
        not pollute bowling stats either, so only players with bowling records
        (total_wickets > 0 OR matches_played > 0 in bowling) enter bowling lists.

        Thin-data tracking
        ------------------
        Players with fewer than MIN_INNINGS = 10 innings are flagged.  The count
        is stored in '_thin_batters' and '_thin_bowlers' for display.
        """
        MIN_INNINGS = 10

        bat_avgs, bat_srs               = [], []
        bat_avgs_loc, bat_srs_loc       = [], []
        bat_avgs_rec, bat_srs_rec       = [], []
        bowl_avgs, bowl_srs, ecos       = [], [], []
        bowl_avgs_loc, bowl_srs_loc, ecos_loc = [], [], []
        bowl_avgs_rec, bowl_srs_rec     = [], []
        exp                             = []
        thin_batters: list[str]         = []
        thin_bowlers: list[str]         = []

        for p in players:
            b = self.calculate_player_batting_stats(p, team, match_date, host, True)
            w = self.calculate_player_bowling_stats(p, team, match_date, host, True)

            # ── Batting: only include players who actually batted ──────────────
            batted = b.get('total_runs', 0) > 0 or b.get('matches_played', 0) > 0
            if batted:
                bat_avgs.append(b['batting_avg'])
                if 'batting_avg_location' in b:
                    bat_avgs_loc.append(b['batting_avg_location'])
                    bat_srs_loc.append(b['batting_sr_location'])
                if 'batting_avg_recent' in b:
                    bat_avgs_rec.append(b['batting_avg_recent'])
                    bat_srs_rec.append(b['batting_sr_recent'])
                if b.get('matches_played', 0) < MIN_INNINGS:
                    thin_batters.append(p)
            # batting SR: display only — collected separately, same DNB filter
            if batted:
                bat_srs.append(b['batting_sr'])

            exp.append(b.get('matches_played', 0))

            # ── Bowling: only include players who actually bowled ──────────────
            bowled = w.get('total_wickets', 0) > 0 or w.get('matches_played', 0) > 0
            if bowled:
                bowl_avgs.append(w['bowling_avg'])
                bowl_srs.append(w['bowling_sr'])
                ecos.append(w['economy'])
                if 'bowling_avg_location' in w:
                    bowl_avgs_loc.append(w['bowling_avg_location'])
                    bowl_srs_loc.append(w['bowling_sr_location'])
                    ecos_loc.append(w['economy_location'])
                if 'bowling_avg_recent' in w:
                    bowl_avgs_rec.append(w['bowling_avg_recent'])
                    bowl_srs_rec.append(w['bowling_sr_recent'])
                if w.get('matches_played', 0) < MIN_INNINGS:
                    thin_bowlers.append(p)

        def sm(lst, fb=None): return float(np.mean(lst)) if lst else (fb if fb is not None else 0.0)

        h2h = self.df_team[
            (self.df_team['Team'] == team) &
            (self.df_team['Opposition'] == opposition) &
            (self.df_team['Start Date'] < match_date)]
        win_rate = float((h2h['Result'] == 'won').mean()) if len(h2h) > 0 else 0.5

        # num_batters / num_bowlers: actual players with records (used in feature row)
        return {
            'team_batting_avg':           sm(bat_avgs),
            'team_batting_avg_location':  sm(bat_avgs_loc, sm(bat_avgs)),
            'team_batting_avg_recent':    sm(bat_avgs_rec, sm(bat_avgs)),
            # Bowling SR (balls per wicket) — primary Test bowling metric
            'team_bowling_sr':            sm(bowl_srs,  80.0),
            'team_bowling_sr_location':   sm(bowl_srs_loc,  sm(bowl_srs, 80.0)),
            'team_bowling_sr_recent':     sm(bowl_srs_rec,  sm(bowl_srs, 80.0)),
            # Bowling average (runs per wicket) — secondary metric
            'team_bowling_avg':           sm(bowl_avgs, 50.0),
            'team_bowling_avg_location':  sm(bowl_avgs_loc, sm(bowl_avgs, 50.0)),
            'team_bowling_avg_recent':    sm(bowl_avgs_rec, sm(bowl_avgs, 50.0)),
            'team_economy':               sm(ecos, 4.0),
            'team_economy_location':      sm(ecos_loc, sm(ecos, 4.0)),
            'team_experience':            sm(exp),
            'num_players':                len(players),
            'win_rate_vs_opposition':     win_rate,
            # Display-only (underscore prefix → skipped by _make_feature_row)
            '_team_batting_sr':           sm(bat_srs),
            '_team_batting_sr_location':  sm(bat_srs_loc, sm(bat_srs)),
            '_team_batting_sr_recent':    sm(bat_srs_rec, sm(bat_srs)),
            '_thin_batters':              thin_batters,
            '_thin_bowlers':              thin_bowlers,
            '_num_batters':               len(bat_avgs),
            '_num_bowlers':               len(bowl_avgs),
        }

    # ── Feature vector builder (shared by training & predict) ─────────────────

    @staticmethod
    def _make_feature_row(pf, sf):
        """
        Build the relative feature dict from primary (pf) vs secondary (sf) team.
        venue_type must already be set in pf before calling.
        """
        features = {}
        for key in pf:
            if key.startswith('_'):
                continue                          # display-only keys — not model features
            if key == 'venue_type':
                features['venue_type'] = pf['venue_type']
            elif key == 'num_players':
                features['players_diff'] = pf[key] - sf[key]
            elif 'bowling' in key or 'economy' in key:
                # lower is better for bowling → invert so higher ratio = stronger team
                features[f'{key}_ratio'] = sf[key] / pf[key] if pf[key] != 0 else 1.0
            else:
                features[f'{key}_ratio'] = pf[key] / sf[key] if sf[key] != 0 else 1.0
        return features

    # ── Training ──────────────────────────────────────────────────────────────

    def prepare_training_data(self):
        """
        THE FIX: add BOTH perspectives per match to guarantee 50/50 balance.
        For every match A vs B:
          row 1 – A as primary  → label = 1 if A won, 0 if A lost
          row 2 – B as primary  → label = 0 if A won, 1 if A lost  (mirror)
        Total rows = 2 x unique matches; win rate = exactly 50%.
        """
        logger.info("Preparing training data ...")
        unique_matches = self.df_team['NumericMatchID'].unique()
        logger.info(f"Processing {len(unique_matches)} unique matches ...")

        X_data, y_data = [], []
        processed = skipped = 0
        v_enc  = {'home': 1.0, 'away': 0.0, 'neutral': 0.5}
        v_flip = {'home': 'away', 'away': 'home', 'neutral': 'neutral'}

        for match_id in unique_matches:
            try:
                rows = self.df_team[self.df_team['NumericMatchID'] == match_id]
                if len(rows) < 2:
                    skipped += 1; continue

                r1, r2     = rows.iloc[0], rows.iloc[1]
                team_a     = r1['Team'];  team_b = r2['Team']
                result_a   = r1['Result']          # 'won' or 'lost'
                match_date = r1['Start Date']
                host       = r1['Host']

                venue_a = 'home' if team_a == host else ('away' if team_b == host else 'neutral')
                venue_b = v_flip[venue_a]

                players_a = self.get_match_players(match_id, team_a)
                players_b = self.get_match_players(match_id, team_b)
                if not players_a or not players_b:
                    skipped += 1; continue

                feat_a = self.calculate_team_features(team_a, players_a, match_date, host, team_b)
                feat_b = self.calculate_team_features(team_b, players_b, match_date, host, team_a)

                fa = dict(feat_a); fa['venue_type'] = v_enc[venue_a]
                fb = dict(feat_b); fb['venue_type'] = v_enc[venue_b]

                label_a = 1 if result_a == 'won' else 0

                # Perspective A
                X_data.append(self._make_feature_row(fa, fb))
                y_data.append(label_a)

                # Perspective B (mirror) — this is the fix
                X_data.append(self._make_feature_row(fb, fa))
                y_data.append(1 - label_a)

                processed += 1
                if processed % 100 == 0:
                    logger.info(f"Processed {processed} matches, skipped {skipped}")

            except Exception as e:
                logger.error(f"Error match {match_id}: {e}")
                skipped += 1

        logger.info(f"Total processed: {processed}, Total skipped: {skipped}")
        X = pd.DataFrame(X_data)
        y = pd.Series(y_data)
        logger.info(f"Feature matrix shape: {X.shape}")
        logger.info(f"Target distribution:\n{y.value_counts()}")
        logger.info(f"Win rate: {y.mean():.2%}")
        if abs(y.mean() - 0.5) > 0.03:
            logger.warning(f"Imbalance still detected: {y.mean():.2%}")
        self.feature_columns = X.columns.tolist()
        return X, y

    def train(self, test_size=0.2):
        logger.info("Starting model training with XGBoost ...")
        X, y = self.prepare_training_data()

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y)
        logger.info(f"Training set: {len(X_train)}, Test set: {len(X_test)}")
        logger.info(f"Train win rate: {y_train.mean():.2%}  |  Test win rate: {y_test.mean():.2%}")

        self.model.fit(X_train, y_train)

        y_pred   = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        logger.info(f"\nModel Accuracy: {accuracy:.4f}")
        logger.info("\nClassification Report:")
        logger.info(classification_report(y_test, y_pred, target_names=['Loss', 'Win']))
        cm = confusion_matrix(y_test, y_pred)
        logger.info(f"\nConfusion Matrix:\n{cm}")

        fi = pd.DataFrame({'feature': self.feature_columns,
                           'importance': self.model.feature_importances_}
                          ).sort_values('importance', ascending=False)
        logger.info("\nTop 15 Features:")
        logger.info(fi.head(15).to_string(index=False))
        return accuracy, fi

    # ── Name resolution & diagnostics ─────────────────────────────────────────

    def find_player_candidates(self, raw_name: str, team: str,
                               max_results: int = 5) -> list[str]:
        """
        Return up to `max_results` player names from the batting+bowling tables
        that are close to `raw_name`, filtered to `team` where possible.

        Strategy (in priority order):
          1. Exact match  (case-insensitive)
          2. Surname match  — last token of the stored name
          3. Initial + surname — stored name contains both tokens of input
          4. Any token overlap — at least one word matches

        Results are filtered to `team` first; if that gives nothing, the filter
        is dropped so cross-team typos are still caught.
        """
        all_players = pd.concat([
            self.df_batting[['Player', 'Team']],
            self.df_bowling[['Player', 'Team']],
        ]).drop_duplicates()

        def _score(stored: str) -> int:
            s = stored.lower()
            r = raw_name.lower()
            if s == r:                          return 4
            r_tokens = set(r.split())
            s_tokens = set(s.split())
            if r_tokens == s_tokens:            return 3
            # surname match (last word)
            if r.split()[-1] == s.split()[-1]:  return 2
            # any token overlap
            if r_tokens & s_tokens:             return 1
            return 0

        for filter_team in (team, None):
            subset = (all_players[all_players['Team'] == filter_team]
                      if filter_team else all_players)
            scored = [(p, _score(p)) for p in subset['Player'].unique()]
            matches = sorted(
                [(p, sc) for p, sc in scored if sc > 0],
                key=lambda x: -x[1]
            )
            if matches:
                return [p for p, _ in matches[:max_results]]

        return []

    def diagnose_xi(self, team: str, players: list[str],
                    match_date=None) -> None:
        """
        Print a per-player lookup table showing exactly what the DB has for
        each player in the XI, so name mismatches are immediately visible.

        Columns: Player (as entered) | DB innings | DB runs | DB wickets | Status
        """
        if match_date is None:
            match_date = datetime.now()

        print(f"\n  {'─'*72}")
        print(f"  PLAYER LOOKUP DIAGNOSTIC — {team}")
        print(f"  {'─'*72}")
        print(f"  {'Player (entered)':<28} {'Innings':>7} {'Runs':>6} {'Wkts':>5}  Status")
        print(f"  {'─'*72}")

        for p in players:
            # Batting
            bd = self.df_batting[self.df_batting['Player'] == p]
            if match_date is not None:
                bd = bd[bd['Start Date'] < match_date]
            innings = len(bd)
            runs    = int(bd['RunsDescending'].sum()) if not bd.empty else 0

            # Bowling
            wd = self.df_bowling[self.df_bowling['Player'] == p]
            if match_date is not None:
                wd = wd[wd['Start Date'] < match_date]
            wkts = int(wd['WktsDescending'].sum()) if not wd.empty else 0

            if innings == 0 and wkts == 0:
                status = "✗ NOT FOUND — check spelling"
            elif innings < 5:
                status = f"⚠ very thin ({innings} innings)"
            else:
                status = "✓"

            print(f"  {p:<28} {innings:>7} {runs:>6} {wkts:>5}  {status}")

        print(f"  {'─'*72}\n")

    # ── Prediction with factor explanations ───────────────────────────────────

    def predict(self, team, team_players, opposition, opp_players=None,
                venue_type='neutral', match_date=None):
        """
        Predict match outcome and return rich factor-level explanations.

        Parameters
        ----------
        team         : str  – team we are predicting for
        team_players : list – playing XI for `team`
        opposition   : str  – opposing team name
        opp_players  : list | None – playing XI for opposition.
                        If None or empty, falls back to their most recent recorded XI.
        venue_type   : 'home' | 'away' | 'neutral'  (from `team`'s perspective)
        match_date   : datetime | None  – defaults to today

        Returns
        -------
        dict with keys:
          team, opposition, venue_type,
          predicted_outcome, win_probability, loss_probability,
          team_features, opposition_features,
          factors  (list of dicts — one per explanatory factor)
        """
        if match_date is None:
            match_date = datetime.now()
        if opp_players is None:
            opp_players = []

        logger.info(f"Predicting: {team} vs {opposition} ({venue_type})")

        host = (team        if venue_type == 'home' else
                opposition  if venue_type == 'away' else 'Neutral')

        # Resolve opposition XI if not provided
        if not opp_players:
            opp_recent = self.df_team[
                (self.df_team['Team'] == opposition) &
                (self.df_team['Start Date'] < match_date)
            ].sort_values('Start Date', ascending=False).head(5)
            for mid in opp_recent['NumericMatchID'].unique():
                opp_players.extend(self.get_match_players(mid, opposition))
                if len(set(opp_players)) >= 11: break
            opp_players = list(set(opp_players))[:11]

        team_feat = self.calculate_team_features(team, team_players, match_date, host, opposition)
        opp_feat  = self.calculate_team_features(opposition, opp_players, match_date, host, team)

        v_enc  = {'home': 1.0, 'away': 0.0, 'neutral': 0.5}
        v_flip = {'home': 'away', 'away': 'home', 'neutral': 'neutral'}
        team_feat['venue_type'] = v_enc[venue_type]
        opp_feat['venue_type']  = v_enc[v_flip[venue_type]]

        feat_row   = self._make_feature_row(team_feat, opp_feat)
        X_pred     = pd.DataFrame([feat_row])[self.feature_columns]
        probs      = self.model.predict_proba(X_pred)[0]
        prediction = self.model.predict(X_pred)[0]

        win_prob  = float(probs[1])
        loss_prob = float(probs[0])

        factors = self._build_factors(team, opposition, team_feat, opp_feat, venue_type)

        return {
            'team':                team,
            'opposition':          opposition,
            'venue_type':          venue_type,
            'predicted_outcome':   'Win' if prediction == 1 else 'Loss',
            'win_probability':     win_prob,
            'loss_probability':    loss_prob,
            'team_features':       team_feat,
            'opposition_features': opp_feat,
            'factors':             factors,
        }

    def _build_factors(self, team, opposition, tf, of_, venue_type):
        """
        Return a list of human-readable factor dicts, each containing:
          name, team_value, opp_value,
          advantage ('team' | 'opposition' | 'neutral'),
          description
        """
        factors = []

        def _adv(better_is_higher, t_val, o_val, threshold=0.5):
            diff = t_val - o_val
            if abs(diff) < threshold: return 'neutral'
            return 'team' if (diff > 0) == better_is_higher else 'opposition'

        # 1. Venue
        factors.append({
            'name':        'Venue',
            'description': f"{'Home' if venue_type == 'home' else ('Away' if venue_type == 'away' else 'Neutral')} ground for {team}",
            'team_value':  'Home'    if venue_type == 'home'   else ('Away'    if venue_type == 'away' else 'Neutral'),
            'opp_value':   'Away'    if venue_type == 'home'   else ('Home'    if venue_type == 'away' else 'Neutral'),
            'advantage':   'team'    if venue_type == 'home'   else ('opposition' if venue_type == 'away' else 'neutral'),
        })

        # 2. Squad depth actually in the database
        nb_t = tf.get('_num_batters', '?')
        nb_o = of_.get('_num_batters', '?')
        nw_t = tf.get('_num_bowlers', '?')
        nw_o = of_.get('_num_bowlers', '?')
        factors.append({
            'name':        'Players with batting records',
            'description': 'How many XI players have batting data in the DB (others likely DNB)',
            'team_value':  nb_t,
            'opp_value':   nb_o,
            'advantage':   _adv(True, float(nb_t), float(nb_o), 1.0),
        })
        factors.append({
            'name':        'Players with bowling records',
            'description': 'How many XI players have bowling data in the DB',
            'team_value':  nw_t,
            'opp_value':   nw_o,
            'advantage':   _adv(True, float(nw_t), float(nw_o), 1.0),
        })

        # ── BATTING ───────────────────────────────────────────────────────────

        # 3. Overall batting average
        factors.append({
            'name':        'Batting Average (career)',
            'description': 'Average runs per dismissal — higher is better',
            'team_value':  round(tf['team_batting_avg'], 2),
            'opp_value':   round(of_['team_batting_avg'], 2),
            'advantage':   _adv(True, tf['team_batting_avg'], of_['team_batting_avg']),
        })

        # 4. Batting average at venue type
        factors.append({
            'name':        'Batting Average at Venue',
            'description': 'Batting average at this type of ground — higher is better',
            'team_value':  round(tf['team_batting_avg_location'], 2),
            'opp_value':   round(of_['team_batting_avg_location'], 2),
            'advantage':   _adv(True, tf['team_batting_avg_location'], of_['team_batting_avg_location']),
        })

        # 5. Recent batting form
        factors.append({
            'name':        'Recent Batting Form (12 months)',
            'description': 'Batting average over the past 12 months — higher is better',
            'team_value':  round(tf['team_batting_avg_recent'], 2),
            'opp_value':   round(of_['team_batting_avg_recent'], 2),
            'advantage':   _adv(True, tf['team_batting_avg_recent'], of_['team_batting_avg_recent']),
        })

        # 6. Batting SR — display only, not a model feature
        factors.append({
            'name':        'Batting Strike Rate (info only)',
            'description': 'Runs per 100 balls — less decisive in Tests; not used by model',
            'team_value':  round(tf['_team_batting_sr'], 1),
            'opp_value':   round(of_['_team_batting_sr'], 1),
            'advantage':   'neutral',   # intentionally never awards an edge
        })

        # ── BOWLING (SR first — most decisive Test metric) ────────────────────

        # 7. Bowling Strike Rate (career) — balls per wicket
        factors.append({
            'name':        'Bowling Strike Rate — career',
            'description': 'Balls bowled per wicket — LOWER is better; primary Test metric',
            'team_value':  round(tf['team_bowling_sr'], 1),
            'opp_value':   round(of_['team_bowling_sr'], 1),
            'advantage':   _adv(False, tf['team_bowling_sr'], of_['team_bowling_sr'], 3.0),
        })

        # 8. Bowling SR at venue
        factors.append({
            'name':        'Bowling Strike Rate — at venue',
            'description': 'Balls per wicket at this type of ground — lower is better',
            'team_value':  round(tf['team_bowling_sr_location'], 1),
            'opp_value':   round(of_['team_bowling_sr_location'], 1),
            'advantage':   _adv(False, tf['team_bowling_sr_location'], of_['team_bowling_sr_location'], 3.0),
        })

        # 9. Bowling SR recent
        factors.append({
            'name':        'Bowling Strike Rate — recent (12 months)',
            'description': 'Balls per wicket over the past 12 months — lower is better',
            'team_value':  round(tf['team_bowling_sr_recent'], 1),
            'opp_value':   round(of_['team_bowling_sr_recent'], 1),
            'advantage':   _adv(False, tf['team_bowling_sr_recent'], of_['team_bowling_sr_recent'], 3.0),
        })

        # 10. Bowling average (career)
        factors.append({
            'name':        'Bowling Average — career',
            'description': 'Runs conceded per wicket — lower is better',
            'team_value':  round(tf['team_bowling_avg'], 2),
            'opp_value':   round(of_['team_bowling_avg'], 2),
            'advantage':   _adv(False, tf['team_bowling_avg'], of_['team_bowling_avg']),
        })

        # 11. Bowling average at venue
        factors.append({
            'name':        'Bowling Average — at venue',
            'description': 'Bowling average at this type of ground — lower is better',
            'team_value':  round(tf['team_bowling_avg_location'], 2),
            'opp_value':   round(of_['team_bowling_avg_location'], 2),
            'advantage':   _adv(False, tf['team_bowling_avg_location'], of_['team_bowling_avg_location']),
        })

        # 12. Bowling average recent
        factors.append({
            'name':        'Bowling Average — recent (12 months)',
            'description': 'Bowling average over the past 12 months — lower is better',
            'team_value':  round(tf['team_bowling_avg_recent'], 2),
            'opp_value':   round(of_['team_bowling_avg_recent'], 2),
            'advantage':   _adv(False, tf['team_bowling_avg_recent'], of_['team_bowling_avg_recent']),
        })

        # 13. Economy rate
        factors.append({
            'name':        'Economy Rate',
            'description': 'Runs conceded per over — lower is better',
            'team_value':  round(tf['team_economy'], 2),
            'opp_value':   round(of_['team_economy'], 2),
            'advantage':   _adv(False, tf['team_economy'], of_['team_economy'], 0.2),
        })

        # ── OTHER ─────────────────────────────────────────────────────────────

        # 14. Head-to-head
        h2h_t = tf['win_rate_vs_opposition'] * 100
        h2h_o = of_['win_rate_vs_opposition'] * 100
        factors.append({
            'name':        'Head-to-Head Win Rate',
            'description': 'Historical win % between these two teams',
            'team_value':  f"{h2h_t:.1f}%",
            'opp_value':   f"{h2h_o:.1f}%",
            'advantage':   _adv(True, tf['win_rate_vs_opposition'],
                                of_['win_rate_vs_opposition'], 0.05),
        })

        # 15. Experience
        factors.append({
            'name':        'Player Experience (avg matches)',
            'description': 'Average career matches played by squad members',
            'team_value':  round(tf['team_experience'], 1),
            'opp_value':   round(of_['team_experience'], 1),
            'advantage':   _adv(True, tf['team_experience'], of_['team_experience'], 5.0),
        })

        return factors

    # ── Model persistence ──────────────────────────────────────────────────────

    def save_model(self, filepath='cricket_match_predictor.pkl',
                   accuracy: float = 0.0, feature_importance=None):
        """Save model + data frames into one pkl for API startup."""
        joblib.dump({
            'model':                  self.model,
            'label_encoder':          self.label_encoder,
            'match_id_label_encoder': self.match_id_label_encoder,
            'feature_columns':        self.feature_columns,
            'match_id_dict':          self.match_id_dict,
            'df_team':                self.df_team,
            'df_batting':             self.df_batting,
            'df_bowling':             self.df_bowling,
            'accuracy':               accuracy,
            'feature_importance':     feature_importance,
        }, filepath)
        logger.info(f"Model saved to {filepath}")

    def load_model(self, filepath='cricket_match_predictor.pkl'):
        d = joblib.load(filepath)
        self.model                  = d['model']
        self.label_encoder          = d['label_encoder']
        self.match_id_label_encoder = d['match_id_label_encoder']
        self.feature_columns        = d['feature_columns']
        self.match_id_dict          = d['match_id_dict']
        logger.info(f"Model loaded from {filepath}")


# ─────────────────────────────────────────────────────────────────────────────
# INPUT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _prompt_team_name(label: str, known_teams: list[str]) -> str:
    """
    Ask the user for a team name and validate it against the teams in the DB.
    Accepts partial, case-insensitive matches and lets the user confirm.
    """
    while True:
        raw = input(f"\n  {label} team name: ").strip()
        if not raw:
            print("  ✗  Please enter a team name.")
            continue

        # Exact match (case-insensitive)
        exact = [t for t in known_teams if t.lower() == raw.lower()]
        if exact:
            return exact[0]

        # Partial match
        partial = [t for t in known_teams if raw.lower() in t.lower()]
        if len(partial) == 1:
            confirm = input(f"  Did you mean '{partial[0]}'? [Y/n]: ").strip().lower()
            if confirm in ('', 'y', 'yes'):
                return partial[0]
        elif len(partial) > 1:
            print(f"  Multiple matches: {', '.join(partial)}")
            print("  Please be more specific.")
        else:
            print(f"  ✗  '{raw}' not found.  Known teams:")
            for t in sorted(known_teams):
                print(f"       • {t}")


def _prompt_xi(team_name: str, predictor) -> list[str]:
    """
    Ask the user to enter 11 player names, one per line.

    Each entry is looked up against the database immediately:
      - Exact match  → accepted silently
      - Close match  → user is shown the DB name and asked to confirm
      - No match     → user is shown candidates and can retry or force-add

    Returns a list of exactly 11 resolved player name strings.
    """
    print(f"\n  Enter the Playing XI for {team_name}.")
    print("  Names are matched against your database as you type.")
    print("  If a name isn't found you'll see suggestions.\n")

    players      = []   # resolved names
    entered_map  = {}   # resolved_name → what the user typed (for display)

    while len(players) < 11:
        slot   = len(players) + 1
        entry  = input(f"  Player {slot:>2}/11: ").strip()
        if not entry:
            print("  ✗  Name cannot be blank.")
            continue
        if entry in players:
            print(f"  ✗  '{entry}' already added.")
            continue

        # ── DB lookup ────────────────────────────────────────────────────────
        bat_exact = predictor.df_batting['Player'] == entry
        bol_exact = predictor.df_bowling['Player'] == entry
        exact_hit = bat_exact.any() or bol_exact.any()

        if exact_hit:
            # Perfect match — accept immediately
            players.append(entry)
            entered_map[entry] = entry
            remaining = 11 - len(players)
            if remaining > 0:
                print(f"         ✓  ({remaining} more to go)")
            continue

        # ── No exact match — search for candidates ────────────────────────
        candidates = predictor.find_player_candidates(entry, team_name)

        if not candidates:
            print(f"  ✗  '{entry}' not found in database and no close matches.")
            force = input("     Force-add anyway? [y/N]: ").strip().lower()
            if force in ('y', 'yes'):
                players.append(entry)
                entered_map[entry] = entry
                remaining = 11 - len(players)
                print(f"         ⚠  Added (no DB data — will use defaults). ({remaining} more to go)")
            continue

        if len(candidates) == 1:
            # Single candidate — prompt to confirm
            c = candidates[0]
            confirm = input(f"  Did you mean '{c}'? [Y/n/force-original]: ").strip().lower()
            if confirm in ('', 'y', 'yes'):
                resolved = c
            elif confirm.startswith('f'):
                resolved = entry
                print(f"         ⚠  Force-added '{entry}' (no DB data — will use defaults).")
            else:
                print("  ↩  Skipped — re-enter the name.")
                continue
            players.append(resolved)
            entered_map[resolved] = entry
            remaining = 11 - len(players)
            if remaining > 0:
                print(f"         ✓  Using '{resolved}'. ({remaining} more to go)")
            continue

        # Multiple candidates — show a numbered list
        print(f"  '{entry}' not found. Close matches:")
        for i, c in enumerate(candidates, 1):
            print(f"    {i}. {c}")
        print(f"    0. None of these — re-enter")
        print(f"    f. Force-add '{entry}' as-is")
        choice = input("  Choose: ").strip().lower()
        if choice == '0' or choice == '':
            continue
        if choice == 'f':
            players.append(entry)
            entered_map[entry] = entry
            print(f"         ⚠  Force-added '{entry}' (no DB data — will use defaults).")
            continue
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                resolved = candidates[idx]
                players.append(resolved)
                entered_map[resolved] = entry
                remaining = 11 - len(players)
                if remaining > 0:
                    print(f"         ✓  Using '{resolved}'. ({remaining} more to go)")
            else:
                print("  ✗  Invalid choice.")
        except ValueError:
            print("  ✗  Invalid choice.")

    print(f"\n  ✓  {team_name} XI confirmed:")
    for i, p in enumerate(players, 1):
        orig = entered_map.get(p, p)
        note = f"  (entered as '{orig}')" if orig != p else ""
        print(f"       {i:>2}. {p}{note}")
    return players


def _prompt_host(team_a: str, team_b: str) -> tuple[str, str, str]:
    """
    Ask which team is playing at home (or if it's a neutral venue).

    Returns
    -------
    host       : str   – the host country string used by the model
    venue_a    : str   – 'home' | 'away' | 'neutral'  (from team_a's perspective)
    venue_b    : str   – mirror of venue_a
    """
    print(f"\n  Where is the match being played?")
    print(f"    1 – {team_a} home ground")
    print(f"    2 – {team_b} home ground")
    print(f"    3 – Neutral venue")

    while True:
        choice = input("  Enter 1, 2, or 3: ").strip()
        if choice == '1':
            return team_a, 'home', 'away'
        elif choice == '2':
            return team_b, 'away', 'home'
        elif choice == '3':
            return 'Neutral', 'neutral', 'neutral'
        else:
            print("  ✗  Please enter 1, 2, or 3.")


def _print_result(result: dict) -> None:
    """Pretty-print the prediction result and factor breakdown."""
    team = result['team']
    opp  = result['opposition']
    tf   = result['team_features']
    of_  = result['opposition_features']

    # ── Outcome ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("MATCH PREDICTION RESULT")
    print("=" * 65)

    venue_label = result['venue_type'].capitalize()
    print(f"  {team} vs {opp}  |  {team} playing {venue_label}\n")

    winner     = team if result['predicted_outcome'] == 'Win' else opp
    loser      = opp  if result['predicted_outcome'] == 'Win' else team
    win_prob   = result['win_probability']
    loss_prob  = result['loss_probability']
    team_prob  = win_prob   # probability from team's perspective
    opp_prob   = loss_prob

    print(f"  Predicted winner  : {winner}")
    print(f"  {team:<28}: {team_prob:.1%} win probability")
    print(f"  {opp:<28}: {opp_prob:.1%} win probability")

    # ── Thin-data warnings ────────────────────────────────────────────────────
    warnings_shown = False
    for label, feat in ((team, tf), (opp, of_)):
        thin_b = feat.get('_thin_batters', [])
        thin_w = feat.get('_thin_bowlers', [])
        nb     = feat.get('_num_batters',  0)
        nw     = feat.get('_num_bowlers',  0)
        if thin_b or thin_w or nb < 7 or nw < 5:
            if not warnings_shown:
                print("\n  ⚠  DATA QUALITY NOTES")
                warnings_shown = True
            if nb < 7:
                print(f"  ⚠  {label}: only {nb} players with batting records "
                      f"(rest likely DNB — batting average may be understated)")
            if thin_b:
                print(f"  ⚠  {label}: thin batting data (<10 innings): "
                      f"{', '.join(thin_b)}")
            if nw < 5:
                print(f"  ⚠  {label}: only {nw} players with bowling records")
            if thin_w:
                print(f"  ⚠  {label}: thin bowling data (<10 matches): "
                      f"{', '.join(thin_w)}")

    # ── Factor breakdown ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("FACTOR BREAKDOWN")
    print("=" * 65)
    t_hdr = team[:12]
    o_hdr = opp[:12]
    print(f"  {'Factor':<40} {t_hdr:>12} {o_hdr:>12} {'Edge':>14}")
    print("  " + "-" * 80)
    for f in result['factors']:
        adv_label = (f"◀ {team[:10]}"  if f['advantage'] == 'team'        else
                     f"{opp[:10]} ▶"   if f['advantage'] == 'opposition'   else
                     "  —  ")
        print(f"  {f['name']:<40} {str(f['team_value']):>12} {str(f['opp_value']):>12} {adv_label:>14}")
    print("=" * 65)


# ─────────────────────────────────────────────────────────────────────────────
# HYPERPARAMETER TUNING  (optional — run once, then use saved model)
# ─────────────────────────────────────────────────────────────────────────────

def tune_hyperparameters(predictor: 'CricketMatchPredictor',
                         n_iter: int = 40,
                         cv: int = 5) -> dict:
    """
    RandomizedSearchCV over the XGBoost hyperparameter space.

    Why RandomizedSearchCV rather than GridSearch?
    -----------------------------------------------
    Grid search over even a modest XGBoost grid explodes combinatorially.
    Randomized search samples `n_iter` random combinations, which gives
    ~90 % of the benefit at ~10 % of the compute.

    cv=5 with stratify ensures each fold is 50/50 win/loss.

    Returns the best params dict (also updates predictor.model in-place).
    """
    from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold

    logger.info("Preparing data for hyperparameter search ...")
    X, y = predictor.prepare_training_data()

    param_dist = {
        'n_estimators':     [100, 200, 300, 400, 500],
        'max_depth':        [3, 4, 5, 6, 7],
        'learning_rate':    [0.01, 0.02, 0.05, 0.1, 0.15],
        'subsample':        [0.6, 0.7, 0.8, 0.9, 1.0],
        'colsample_bytree': [0.6, 0.7, 0.8, 0.9, 1.0],
        'min_child_weight': [1, 3, 5, 7],
        'gamma':            [0, 0.1, 0.2, 0.3, 0.5],
        'reg_alpha':        [0, 0.01, 0.1, 0.5, 1.0],   # L1
        'reg_lambda':       [1, 1.5, 2.0, 3.0, 5.0],    # L2
    }

    base_model = XGBClassifier(
        random_state=42,
        n_jobs=-1,
        eval_metric='logloss',
        use_label_encoder=False,
    )

    cv_strategy = StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)

    search = RandomizedSearchCV(
        estimator=base_model,
        param_distributions=param_dist,
        n_iter=n_iter,
        scoring='accuracy',
        cv=cv_strategy,
        verbose=1,
        random_state=42,
        n_jobs=-1,
    )

    logger.info(f"Running {n_iter} random trials × {cv}-fold CV ...")
    search.fit(X, y)

    best_params = search.best_params_
    best_score  = search.best_score_

    logger.info(f"Best CV accuracy : {best_score:.4f}")
    logger.info(f"Best params      : {best_params}")

    print("\n" + "=" * 60)
    print("HYPERPARAMETER TUNING RESULTS")
    print("=" * 60)
    print(f"  Best CV accuracy : {best_score:.4f}")
    print(f"  Best parameters  :")
    for k, v in sorted(best_params.items()):
        print(f"    {k:<25}: {v}")

    # Re-train on full dataset with best params, update predictor.model
    best_model = XGBClassifier(
        **best_params,
        random_state=42,
        n_jobs=-1,
        eval_metric='logloss',
        use_label_encoder=False,
    )
    best_model.fit(X, y)
    predictor.model = best_model
    logger.info("predictor.model replaced with tuned model (trained on full dataset)")

    return best_params


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    # ── Step 1: DB connection ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 1 — DATABASE CONNECTION TEST")
    print("=" * 60)
    if not test_connection():
        raise SystemExit("Cannot connect to DB. Check DB_CONFIG.")

    # ── Step 2: Train ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2 — TRAIN MODEL")
    print("=" * 60)
    predictor = CricketMatchPredictor()
    predictor.load_data_from_db()
    accuracy, fi = predictor.train(test_size=0.2)

    print("\n" + "=" * 60)
    print("FEATURE IMPORTANCE (TOP 15)")
    print("=" * 60)
    print(fi.head(15).to_string(index=False))

    # ── Step 2b: Optional hyperparameter tuning ───────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2b — HYPERPARAMETER TUNING (optional)")
    print("=" * 60)
    print("  RandomizedSearchCV over XGBoost hyperparameters.")
    print("  This takes a few minutes but typically improves accuracy by 1–3 pp.")
    do_tune = input("  Run hyperparameter tuning? [y/N]: ").strip().lower()
    if do_tune in ('y', 'yes'):
        n_iter_input = input("  Number of random trials [default 40]: ").strip()
        n_iter = int(n_iter_input) if n_iter_input.isdigit() else 40
        best_params = tune_hyperparameters(predictor, n_iter=n_iter, cv=5)
    else:
        print("  Skipping — using default hyperparameters.")

    predictor.save_model('cricket_match_predictor.pkl', accuracy=accuracy, feature_importance=fi)
    print(f"\n  Model saved to cricket_match_predictor.pkl (includes data frames for API)")

    # ── Step 3: Interactive prediction ───────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3 — MATCH PREDICTION")
    print("=" * 60)
    print("  Enter the two Playing XIs and the match location.")
    print("  Names are matched against the database as you type.")

    known_teams = sorted(predictor.df_team['Team'].unique().tolist())

    def _run_one_prediction():
        team_a = _prompt_team_name("Team A (the team you want to predict for)", known_teams)
        xi_a   = _prompt_xi(team_a, predictor)

        remaining_teams = [t for t in known_teams if t != team_a]
        team_b = _prompt_team_name("Team B (the opposition)", remaining_teams)
        xi_b   = _prompt_xi(team_b, predictor)

        host, venue_a, _venue_b = _prompt_host(team_a, team_b)

        # ── Diagnostic: show per-player DB lookup before predicting ──────────
        print("\n  Running player lookup diagnostic ...")
        predictor.diagnose_xi(team_a, xi_a)
        predictor.diagnose_xi(team_b, xi_b)

        proceed = input("  Proceed with prediction? [Y/n]: ").strip().lower()
        if proceed in ('n', 'no'):
            print("  Prediction cancelled. Re-enter the XIs to try again.")
            return

        print("\n  Running prediction ...")
        result = predictor.predict(
            team=team_a,
            team_players=xi_a,
            opposition=team_b,
            opp_players=xi_b,
            venue_type=venue_a,
        )
        _print_result(result)

    _run_one_prediction()

    while True:
        again = input("\n  Run another prediction with the same trained model? [y/N]: ").strip().lower()
        if again not in ('y', 'yes'):
            print("\n  Done.")
            break
        _run_one_prediction()