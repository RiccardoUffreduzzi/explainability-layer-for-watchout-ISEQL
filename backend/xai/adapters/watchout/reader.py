"""``SqliteWatchOutReader``: the ``WatchOutReader`` port over one read-only connection.

It joins the three adapters: database rows (``SqliteRecords``), detections
(``LiveDetections``) and the values of WatchOut's code (``WatchOutCodeFacts``).
"""

import sqlite3

from xai.adapters.watchout.code_facts import WatchOutCodeFacts
from xai.adapters.watchout.detections_live import LiveDetections
from xai.adapters.watchout.records import SqliteRecords


class SqliteWatchOutReader(SqliteRecords, LiveDetections, WatchOutCodeFacts):
    """Reads WatchOut through a connection from ``open_read_only``"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        SqliteRecords.__init__(self, conn)
        LiveDetections.__init__(self, conn)
