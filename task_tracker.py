# -*- coding: utf-8 -*-
"""Download task tracker + Baidu upload background worker."""

import os, json, time, threading, queue

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TaskTracker:
    """Tracks downloaded files and uploads them to Baidu in background."""

    def __init__(self, cfg=None, remote_dir=None):
        self.task_id = str(int(time.time() * 1000))
        self.files = []
        self._queue = queue.Queue()
        self._cfg = cfg or load_config()
        self._remote_dir = remote_dir or (self._cfg.get("upload_dir", "/apps/downloaderVideo") if self._cfg else "/apps/downloaderVideo")
        self._thread = None
        self._running = False
        self._uploaded = 0
        self._failed = 0

    def record(self, filepath):
        """Record a downloaded file and queue for upload."""
        if not filepath or not os.path.exists(filepath):
            return
        self.files.append(filepath)
        if self._running:
            self._queue.put(filepath)

    def record_result(self, result):
        """Normalize download result and record all file paths."""
        if not result:
            return
        if isinstance(result, str):
            self.record(result)
        elif isinstance(result, (list, tuple)):
            for r in result:
                if isinstance(r, str):
                    self.record(r)

    def start_upload(self):
        """Start background upload thread."""
        if not self._cfg:
            print("[BAIDU] No config. Run: python upload_baidu.py --auth")
            return
        from upload_baidu import upload_file, get_access_token

        # Verify token before starting
        token = get_access_token(self._cfg)
        if not token:
            print("[BAIDU] No valid token. Run: python upload_baidu.py --auth")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._upload_worker,
            args=(self._cfg, self.task_id, self._remote_dir),
            daemon=True,
        )
        self._thread.start()
        print("[BAIDU] Upload worker started (task: {})".format(self.task_id))

    def _upload_worker(self, cfg, task_id, remote_dir):
        from upload_baidu import upload_file, get_access_token
        processed = set()
        while self._running or not self._queue.empty():
            try:
                fp = self._queue.get(timeout=3)
                if fp in processed:
                    continue
                processed.add(fp)
                if upload_file(fp, cfg, remote_dir):
                    self._uploaded += 1
                else:
                    self._failed += 1
            except queue.Empty:
                if not self._running:
                    break
            except Exception as e:
                print("[BAIDU] Upload worker error: " + str(e)[:80])

    def wait(self):
        """Wait for all uploads to finish."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=300)
        total = self._uploaded + self._failed
        if total > 0:
            print("[BAIDU] Task {} complete: {}/{} uploaded".format(
                self.task_id, self._uploaded, total))

    def save_log(self):
        """Save download task log."""
        log_dir = os.path.join(ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log = {
            "task_id": self.task_id,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": self.files,
            "uploaded": self._uploaded,
            "failed": self._failed,
        }
        log_path = os.path.join(log_dir, "task_{}.json".format(self.task_id))
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
