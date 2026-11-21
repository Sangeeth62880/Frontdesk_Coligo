"""Application-owned automatic close sweep; safe with multiple app workers."""
import logging
import threading

import psycopg
from psycopg.rows import dict_row

from frontdesk import service

logger = logging.getLogger(__name__)


def run_once(database_url):
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as db:
        now = db.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        return service.auto_close(db, now)


class Sweeper:
    def __init__(self, database_url, interval=60):
        self.database_url = database_url
        self.interval = interval
        self.stop_event = threading.Event()
        self.first_success = threading.Event()
        self.thread = threading.Thread(target=self.run, name="frontdesk-auto-close", daemon=True)

    def run(self):
        while not self.stop_event.is_set():
            try:
                result = run_once(self.database_url)
                self.first_success.set()
                if result["closed_count"]:
                    logger.info("Automatically closed %s ticket(s)", result["closed_count"])
            except Exception:
                # A failed sweep rolls back its whole transaction; retry next tick.
                logger.exception("Auto-close sweep failed; will retry")
            self.stop_event.wait(self.interval)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=12)
