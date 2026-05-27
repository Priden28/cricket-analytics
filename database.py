import logging
import os
import time
from datetime import datetime
from typing import Optional

import pandas as pd

from config import DB_CONFIG

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------
_pool = None
_use_connector = bool(os.environ.get("INSTANCE_CONNECTION_NAME", ""))

_icn_debug = os.environ.get("INSTANCE_CONNECTION_NAME", "NOT_SET")
logger.info(f"DATABASE INIT — INSTANCE_CONNECTION_NAME='{_icn_debug}'")
logger.info(f"DATABASE INIT — all env keys: {[k for k in os.environ.keys() if 'INSTANCE' in k or 'SQL' in k or 'DB' in k]}")
logger.info(f"Database mode: {'Cloud SQL connector' if _use_connector else 'direct TCP'}")


def _make_pool():
    global _pool, _use_connector
    # Re-read env var in case it was set after module import
    icn = os.environ.get("INSTANCE_CONNECTION_NAME", "")
    _use_connector = bool(icn)

    if _use_connector:
        logger.info(f"Using Cloud SQL connector for {icn}")
        from google.cloud.sql.connector import Connector
        import pg8000
        import threading

        _connector = Connector()
        _conn_lock = threading.Lock()
        _conn_list = []

        def _get_connector_conn():
            return _connector.connect(
                icn,
                "pg8000",
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                db=DB_CONFIG["dbname"],
            )

        # Store connector function as a marker — pool is None for connector path
        _pool = _get_connector_conn  # callable, not a pool
        logger.info("Cloud SQL connector ready")
    else:
        logger.info(f"Creating direct TCP pool to {DB_CONFIG['host']}:{DB_CONFIG['port']}")
        import psycopg2.pool as pg_pool
        _pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=5, **DB_CONFIG)
        logger.info("Direct TCP pool created")

    return _pool


def _get_pool():
    global _pool
    if _pool is None:
        _make_pool()
    return _pool


def _is_connector():
    """True when using Cloud SQL connector (pool is a callable, not a pool object)."""
    return callable(_pool)


class DatabaseManager:

    def __init__(self):
        self.ensure_constraints()

    def ensure_constraints(self):
        statements = [
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'batting_unique' AND conrelid = 'batting'::regclass
                ) THEN
                    ALTER TABLE batting DROP CONSTRAINT batting_unique;
                END IF;
                ALTER TABLE batting
                ADD CONSTRAINT batting_unique
                UNIQUE ("Player", "RunsDescending", "BF", "4s", "6s",
                        "Opposition", "Ground", "Start Date", "Inns", "Not Out", "Team");
            END $$;
            """,
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'team_unique' AND conrelid = 'team'::regclass
                ) THEN
                    ALTER TABLE team DROP CONSTRAINT team_unique;
                END IF;
                ALTER TABLE team
                ADD CONSTRAINT team_unique
                UNIQUE ("Team", "ScoreDescending", "Wickets", "Overs",
                        "Opposition", "Ground", "Start Date", "Inns");
            END $$;
            """,
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'bowling_unique' AND conrelid = 'bowling'::regclass
                ) THEN
                    ALTER TABLE bowling DROP CONSTRAINT bowling_unique;
                END IF;
                ALTER TABLE bowling
                ADD CONSTRAINT bowling_unique
                UNIQUE ("Player", "Overs", "Mdns", "Runs", "WktsDescending",
                        "Opposition", "Ground", "Start Date", "Inns", "Team");
            END $$;
            """,
        ]
        conn, cursor = self.get_connection()
        try:
            for stmt in statements:
                cursor.execute(stmt)
            conn.commit()
            logger.info("Unique constraints verified/created")
        except Exception as e:
            conn.rollback()
            logger.error(f"ensure_constraints failed: {e}")
            raise
        finally:
            self.release(conn, cursor)

    def get_connection(self):
        for attempt in range(5):
            try:
                _get_pool()  # ensure pool is initialised
                if _is_connector():
                    # Cloud SQL connector — create a fresh connection each time
                    conn = _pool()
                    conn.autocommit = False
                    cursor = conn.cursor()
                else:
                    conn = _pool.getconn()
                    conn.autocommit = False
                    cursor = conn.cursor()
                return conn, cursor
            except Exception as e:
                logger.warning(f"Pool getconn attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        raise RuntimeError("Could not obtain a database connection after 5 attempts")

    @staticmethod
    def release(conn, cursor):
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                if _is_connector():
                    conn.close()  # connector connections are not pooled
                else:
                    _pool.putconn(conn)
        except Exception:
            pass

    def fetch_latest_date(self, table_name: str) -> Optional[datetime]:
        conn, cursor = self.get_connection()
        try:
            cursor.execute(f'SELECT MAX("Start Date") FROM "{table_name}"')
            result = cursor.fetchone()[0]
            if result is None:
                return None
            if isinstance(result, datetime):
                return result
            return datetime.strptime(str(result).split()[0], "%Y-%m-%d")
        except Exception as e:
            logger.error(f"fetch_latest_date({table_name}): {e}")
            return None
        finally:
            self.release(conn, cursor)

    def fetch_unique_batting_players(self) -> list[str]:
        conn, cursor = self.get_connection()
        try:
            cursor.execute('SELECT DISTINCT "Player" FROM batting ORDER BY "Player"')
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"fetch_unique_batting_players: {e}")
            return []
        finally:
            self.release(conn, cursor)

    def fetch_unique_bowling_players(self) -> list[str]:
        conn, cursor = self.get_connection()
        try:
            cursor.execute('SELECT DISTINCT "Player" FROM bowling ORDER BY "Player"')
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"fetch_unique_bowling_players: {e}")
            return []
        finally:
            self.release(conn, cursor)

    def fetch_batting_data_by_player(self, player_name: str) -> Optional[pd.DataFrame]:
        conn, cursor = self.get_connection()
        try:
            cursor.execute(
                'SELECT "Player", "RunsDescending", "SR", "Opposition", "Start Date" '
                'FROM batting WHERE "Player" = %s',
                (player_name,),
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return pd.DataFrame(rows, columns=cols)
        except Exception as e:
            logger.error(f"fetch_batting_data_by_player({player_name}): {e}")
            return None
        finally:
            self.release(conn, cursor)

    def fetch_bowling_data_by_player(self, player_name: str) -> Optional[pd.DataFrame]:
        conn, cursor = self.get_connection()
        try:
            cursor.execute(
                'SELECT "Player", "WktsDescending", "Runs", "Econ", "Opposition", "Start Date" '
                'FROM bowling WHERE "Player" = %s',
                (player_name,),
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return pd.DataFrame(rows, columns=cols)
        except Exception as e:
            logger.error(f"fetch_bowling_data_by_player({player_name}): {e}")
            return None
        finally:
            self.release(conn, cursor)

    def fetch_all(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        conn, cursor = self.get_connection()
        try:
            cursor.execute('SELECT * FROM team')
            df_team = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
            cursor.execute('SELECT * FROM batting')
            df_batting = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
            cursor.execute('SELECT * FROM bowling')
            df_bowling = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
            return df_team, df_batting, df_bowling
        except Exception as e:
            logger.error(f"fetch_all: {e}")
            raise
        finally:
            self.release(conn, cursor)

    def bulk_insert_team(self, records: list[tuple]) -> int:
        if not records:
            return 0
        query = """
            INSERT INTO team
                ("Team", "ScoreDescending", "Overs", "RPO", "Lead", "Inns",
                 "Result", "Opposition", "Ground", "Start Date", "Declared", "Wickets")
            VALUES %s
            ON CONFLICT ON CONSTRAINT team_unique DO NOTHING
        """
        return self._bulk_execute(query, records, "team")

    def bulk_insert_batting(self, records: list[tuple]) -> int:
        if not records:
            return 0
        query = """
            INSERT INTO batting
                ("Player", "RunsDescending", "BF", "4s", "6s", "SR", "Inns",
                 "Opposition", "Ground", "Start Date", "Not Out", "Team")
            VALUES %s
            ON CONFLICT ON CONSTRAINT batting_unique DO NOTHING
        """
        return self._bulk_execute(query, records, "batting")

    def bulk_insert_bowling(self, records: list[tuple]) -> int:
        if not records:
            return 0
        query = """
            INSERT INTO bowling
                ("Player", "Overs", "Mdns", "Runs", "WktsDescending", "Econ",
                 "Inns", "Opposition", "Ground", "Start Date", "Team")
            VALUES %s
            ON CONFLICT ON CONSTRAINT bowling_unique DO NOTHING
        """
        return self._bulk_execute(query, records, "bowling")

    def _bulk_execute(self, query: str, records: list[tuple], label: str) -> int:
        conn, cursor = self.get_connection()
        try:
            from psycopg2.extras import execute_values
            returning_query = query.rstrip().rstrip(";")
            if "RETURNING" not in returning_query.upper():
                returning_query += " RETURNING 1"
            execute_values(cursor, returning_query, records, page_size=500)
            inserted = len(cursor.fetchall())
            conn.commit()
            logger.info(f"bulk_insert {label}: {inserted} rows inserted")
            return inserted
        except Exception as e:
            conn.rollback()
            logger.error(f"bulk_insert {label} failed: {e}")
            raise
        finally:
            self.release(conn, cursor)
