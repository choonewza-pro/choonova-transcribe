"""
Core SQLite Database Connection Manager.
Provides thread-safe connection factory with WAL mode & busy timeout for high concurrency.
"""

import os
import sqlite3
from app.core.config import DATA_DIR, JOBS_DB_PATH


def get_db_connection() -> sqlite3.Connection:
    """
    Returns an SQLite database connection with:
    - Row factory enabled for dict-like row access
    - WAL (Write-Ahead Logging) journal mode for concurrent reads/writes
    - 30-second busy timeout to avoid 'database is locked' errors
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(JOBS_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    
    # Enable WAL mode and busy timeout for concurrent subprocess/multithread access
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except sqlite3.OperationalError:
        pass  # Ignore if locked or temporarily unavailable in worker contexts
        
    return conn
