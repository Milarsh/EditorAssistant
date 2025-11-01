import os
from datetime import datetime, timezone

LOG_DIR = "./log"

class Logger:
    def __init__(self, logger_type: str):
        self._path = None
        self._logger_type = logger_type
        self._file = None

    def ensure_log_dir(self):
        os.makedirs(os.path.join(LOG_DIR, self._logger_type), exist_ok=True)

    def _log_path_for_today(self) -> str:
        return os.path.join(LOG_DIR, self._logger_type, datetime.now(timezone.utc).strftime(f"{self._logger_type}_%Y-%m_%d.log"))

    def _reopen_if_needed(self):
        path = self._log_path_for_today()
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