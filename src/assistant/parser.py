import os
import time
from datetime import datetime, timezone

from src.assistant.vk_parser import run_vk_cycle
from src.assistant.rss_parser import run_rss_cycle
from src.assistant.tg_parser import run_tg_cycle
from src.utils.logger import Logger

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))

logger = Logger("parser")

def run_cycle():
    logger.ensure_log_dir()
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-START] {start}")

    total_added = 0
    total_added += run_vk_cycle(logger)
    total_added += run_rss_cycle(logger)
    total_added += run_tg_cycle(logger)

    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-END] {end} added={total_added}")

def main():
    logger.ensure_log_dir()
    logger.write("[PARSER] Parser started")
    interval = POLL_INTERVAL
    while True:
        run_cycle()
        time.sleep(interval)

if __name__ == "__main__":
    main()