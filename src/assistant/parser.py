import os
import time
from datetime import datetime, timezone

from src.assistant.vk_parser import run_vk_cycle
from src.assistant.rss_parser import run_rss_cycle

LOG_DIR = "./log"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))

def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def log_path_for_today() -> str:
    return os.path.join(LOG_DIR, datetime.now(timezone.utc).strftime("parser_%Y-%m_%d.log"))

class DailyFileLogger:
    def __init__(self):
        self._path = None
        self._file = None

    def _reopen_if_needed(self):
        path = log_path_for_today()
        if path != self._path:
            if self._file:
                self._file.close()
            self._path = path
            self._file = open(self._path, "a", encoding="utf-8")

    def write(self, line: str):
        self._reopen_if_needed()
        log_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._file.write(f"{log_time} {line.rstrip()}\n")
        self._file.flush()

logger = DailyFileLogger()


def run_cycle():
    ensure_log_dir()

    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-START] {start}")

    total_added = 0
    total_added += run_vk_cycle(logger)
    total_added += run_rss_cycle(logger)

    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-END] {end} added={total_added}")

def main():
    logger.write("[PARSER] Parser started")
    interval = POLL_INTERVAL
    while True:
        run_cycle()
        time.sleep(interval)

if __name__ == "__main__":
    main()