import logging
import time
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2 import pool as pg_pool
import pandas as pd

from config import DB_CONFIG

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool – created once at import time
# ---------------------------------------------------------------------------
_pool: Optional[pg_pool.ThreadedConnectionPool] = None


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=5, **DB_CONFIG)
        logger.info("PostgreSQL connection pool created (min=1, max=5)")
    return _pool


class DatabaseManager:

    def __init__(self):
        self.ensure_constraints()

    # ------------------------------------------------------------------
    # Constraints – must exist for ON CONFLICT DO NOTHING to work
    # ------------------------------------------------------------------

    def ensure_constraints(self):
        """
        Idempotently add UNIQUE constraints to all three tables.
        ON CONFLICT DO NOTHING is a no-op without them.
        Safe to call multiple times – uses IF NOT EXISTS logic via
        a DO $$ block so it won't error if the constraint already exists.

        Constraint philosophy: identify a *specific innings* by every
        observable column, so that two genuinely different innings that
        happen to share some values (e.g. two players scoring 50 at the
        same ground on the same day) are never collapsed into one row.
        """
        statements = [
            # Drop old, too-narrow constraint if it exists, then add the
            # corrected one.  DROP … IF EXISTS is safe to re-run.
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
            logger.info("Unique constraints verified/created on team, batting, bowling")
        except Exception as e:
            conn.rollback()
            logger.error(f"ensure_constraints failed: {e}")
            raise
        finally:
            self.release(conn, cursor)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def get_connection(self):
        for attempt in range(5):
            try:
                conn = _get_pool().getconn()
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
                _get_pool().putconn(conn)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

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
        """Fetch all three tables in one shot for analytics."""
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

    # ------------------------------------------------------------------
    # Bulk inserts  (ON CONFLICT DO NOTHING = PostgreSQL's INSERT IGNORE)
    # ------------------------------------------------------------------

    def bulk_insert_team(self, records: list[tuple]) -> int:
        if not records:
            return 0
        # execute_values uses %s as a single placeholder for a whole row tuple
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
        """
        Execute a bulk INSERT … ON CONFLICT DO NOTHING and return the
        number of rows *actually* inserted.

        psycopg2's executemany sets cursor.rowcount to the result of only
        the *last* statement, so it cannot be used to count total inserts.
        Instead we append RETURNING 1 and count the returned rows, which
        gives an exact tally regardless of batch size.
        """
        conn, cursor = self.get_connection()
        try:
            from psycopg2.extras import execute_values

            returning_query = query.rstrip().rstrip(";")
            if "RETURNING" not in returning_query.upper():
                returning_query += " RETURNING 1"

            execute_values(cursor, returning_query, records, page_size=500)
            inserted = len(cursor.fetchall())
            skipped = len(records) - inserted
            conn.commit()
            logger.info(
                f"bulk_insert {label}: {inserted} rows inserted, "
                f"{skipped} duplicates skipped (total attempted: {len(records)})"
            )
            return inserted
        except Exception as e:
            conn.rollback()
            logger.error(f"bulk_insert {label} failed: {e}")
            raise
        finally:
            self.release(conn, cursor)