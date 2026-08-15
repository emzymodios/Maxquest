"""
Chỉ chứa logic auto quest, không có dashboard.
"""

import threading
import time
import random
import traceback
import base64
import json as _json
import requests
import re
from datetime import datetime, timezone
from typing import Optional

import database

API_BASE = "https://discord.com/api/v9"
HEARTBEAT_INTERVAL = 20
SUPPORTED_TASKS = [
    "WATCH_VIDEO",
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY",
    "WATCH_VIDEO_ON_MOBILE",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

class Colors:
    RESET = "\033[0m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"


def _get(d, *keys):
    if d is None:
        return None
    for k in keys:
        if k in d:
            return d[k]
    return None


def fetch_latest_build_number() -> int:
    FALLBACK = 504649
    try:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
        r = requests.get("https://discord.com/app", headers={"User-Agent": ua}, timeout=15)
        if r.status_code != 200:
            return FALLBACK
        scripts = re.findall(r'/assets/([a-f0-9]+)\.js', r.text)
        if not scripts:
            scripts_alt = re.findall(r'src="(/assets/[^"]+\.js)"', r.text)
            scripts = [s.split('/')[-1].replace('.js', '') for s in scripts_alt]
        if not scripts:
            return FALLBACK
        for asset_hash in scripts[-5:]:
            try:
                ar = requests.get(
                    f"https://discord.com/assets/{asset_hash}.js",
                    headers={"User-Agent": ua}, timeout=15
                )
                m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar.text)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
        return FALLBACK
    except Exception:
        return FALLBACK


def make_super_properties(build_number: int) -> str:
    obj = {
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_version": "1.0.9175",
        "os_version": "10.0.26100",
        "os_arch": "x64",
        "app_arch": "x64",
        "system_locale": "en-US",
        "browser_user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "discord/1.0.9175 Chrome/128.0.6613.186 "
            "Electron/32.2.7 Safari/537.36"
        ),
        "browser_version": "32.2.7",
        "client_build_number": build_number,
        "native_build_number": 59498,
        "client_event_source": None,
    }
    return base64.b64encode(_json.dumps(obj).encode()).decode()


class WorkerAPI:
    def __init__(self, token: str, build_number: int):
        self.token = token
        self.session = requests.Session()
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "discord/1.0.9175 Chrome/128.0.6613.186 "
            "Electron/32.2.7 Safari/537.36"
        )
        sp = make_super_properties(build_number)
        self.session.headers.update({
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": ua,
            "X-Super-Properties": sp,
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
        })

    def get(self, path: str):
        return self.session.get(f"{API_BASE}{path}")

    def post(self, path: str, payload=None):
        return self.session.post(f"{API_BASE}{path}", json=payload)


# ── Quest helpers ─────────────────────────────────────────────────────────────

def get_task_config(quest):
    cfg = quest.get("config", {})
    return _get(cfg, "taskConfig", "task_config", "taskConfigV2", "task_config_v2")


def get_quest_name(quest):
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    name = _get(msgs, "questName", "quest_name")
    if name:
        return name.strip()
    game = _get(msgs, "gameTitle", "game_title")
    if game:
        return game.strip()
    app_name = cfg.get("application", {}).get("name")
    if app_name:
        return app_name
    return f"Quest#{quest.get('id', '?')}"


def get_expires_at(quest):
    cfg = quest.get("config", {})
    return _get(cfg, "expiresAt", "expires_at")


def get_user_status(quest):
    us = _get(quest, "userStatus", "user_status")
    return us if isinstance(us, dict) else {}


def is_completable(quest):
    expires = get_expires_at(quest)
    if expires:
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc):
                return False
        except Exception:
            pass
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc:
        return False
    tasks = tc["tasks"]
    return any(tasks.get(t) is not None for t in SUPPORTED_TASKS)


def is_enrolled(quest):
    us = get_user_status(quest)
    return bool(_get(us, "enrolledAt", "enrolled_at"))


def is_completed(quest):
    us = get_user_status(quest)
    return bool(_get(us, "completedAt", "completed_at"))


def get_task_type(quest):
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc:
        return None
    for t in SUPPORTED_TASKS:
        if tc["tasks"].get(t) is not None:
            return t
    return None


def get_seconds_needed(quest):
    tc = get_task_config(quest)
    task_type = get_task_type(quest)
    if not tc or not task_type:
        return 0
    return tc["tasks"][task_type].get("target", 0)


def get_seconds_done(quest):
    task_type = get_task_type(quest)
    if not task_type:
        return 0
    us = get_user_status(quest)
    progress = us.get("progress", {})
    return progress.get(task_type, {}).get("value", 0)


def get_enrolled_at(quest):
    us = get_user_status(quest)
    return _get(us, "enrolledAt", "enrolled_at")


# ── Worker ─────────────────────────────────────────────────────────────────────

class QuestWorker(threading.Thread):
    """Runs auto-completion for one Discord account."""

    def __init__(self, token: str, user_id: str, username: str,
                 poll_interval: int = 60, auto_accept: bool = True,
                 stop_event: threading.Event = None,
                 max_cycles_no_quest: int = 30):
        super().__init__(daemon=True)
        self.token = token
        self.user_id = user_id
        self.username = username
        self.poll_interval = poll_interval
        self.auto_accept = auto_accept
        self._stop = stop_event or threading.Event()
        self._api: Optional[WorkerAPI] = None
        self._build_number = 0
        self._session_id: Optional[int] = None
        self._completed_ids: set = set()
        self._running = False
        self._last_status = "idle"
        self._status_msg = "Khoi dong..."
        self._logger = None
        self._forced_stop = False
        
        self._max_cycles_no_quest = max_cycles_no_quest
        self._cycles_without_new_quest = 0
        
        self._stats = {
            "quests_completed": 0,
            "quests_enrolled": 0,
            "cycles_run": 0,
            "runtime_seconds": 0,
            "start_time": None,
            "last_new_quest_at": None,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> str:
        return self._last_status

    @property
    def status_message(self) -> str:
        return self._status_msg

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def get_stats_summary(self) -> str:
        if self._stats["start_time"]:
            elapsed = int(time.time() - self._stats["start_time"])
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            runtime_str = f"{hours}h {minutes}m {seconds}s"
        else:
            runtime_str = "0s"
        
        return (
            f"Completed: {self._stats['quests_completed']} | "
            f"Enrolled: {self._stats['quests_enrolled']} | "
            f"Cycles: {self._stats['cycles_run']} | "
            f"Runtime: {runtime_str}"
        )

    def set_logger(self, logger_func):
        self._logger = logger_func

    def _log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info":     f"[{self.username}][INFO]   ",
            "ok":       f"[{self.username}][  OK]   ",
            "warn":     f"[{self.username}][WARN]   ",
            "error":    f"[{self.username}][ ERR]   ",
            "progress": f"[{self.username}][PROG]   ",
        }.get(level, f"[{self.username}][{level.upper()}]")
        
        log_msg = f"{ts} {prefix} {msg}"
        print(log_msg)
        
        if self._logger:
            self._logger(log_msg)

    def _fetch_build(self):
        self._log("Dang lay build number...")
        self._build_number = fetch_latest_build_number()
        self._api = WorkerAPI(self.token, self._build_number)
        self._log(f"Build number: {self._build_number}", "ok")

    def _fetch_quests(self) -> list:
        try:
            r = self._api.get("/quests/@me")

            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    excluded = data.get("excluded_quests", [])
                    blocked = _get(data, "quest_enrollment_blocked_until")
                    if blocked:
                        self._log(f"Enrollment blocked until: {blocked}", "warn")
                    if excluded:
                        self._log(f"{len(excluded)} quest(s) excluded", "info")
                    return data.get("quests", [])
                elif isinstance(data, list):
                    return data
                return []

            elif r.status_code == 429:
                retry_after = r.json().get("retry_after", 10)
                self._log(f"Rate limited – cho {retry_after}s", "warn")
                time.sleep(retry_after)
                return self._fetch_quests()
            else:
                self._log(f"Quest fetch loi ({r.status_code}): {r.text[:200]}", "warn")
                return []

        except Exception as e:
            self._log(f"Loi fetch quests: {e}", "error")
            if True:
                traceback.print_exc()
            return []

    def _enroll_quest(self, quest: dict) -> bool:
        name = get_quest_name(quest)
        qid = quest["id"]
        for attempt in range(1, 4):
            try:
                r = self._api.post(f"/quests/{qid}/enroll", {
                    "location": 11,
                    "is_targeted": False,
                    "metadata_raw": None,
                    "metadata_sealed": None,
                    "traffic_metadata_raw": quest.get("traffic_metadata_raw"),
                    "traffic_metadata_sealed": quest.get("traffic_metadata_sealed"),
                })
                if r.status_code == 429:
                    retry_after = r.json().get("retry_after", 5)
                    self._log(f"Rate limited enroll (lan {attempt}/3) – cho {retry_after + 1}s", "warn")
                    time.sleep(retry_after + 1)
                    continue
                if r.status_code in (200, 201, 204):
                    self._stats["quests_enrolled"] += 1
                    self._log(f"Da nhan quest: {name}", "ok")
                    database.log_quest(self._get_token_id(), name, qid, get_task_type(quest) or "", "enrolled", "success")
                    return True
                self._log(f"Enroll that bai ({r.status_code}): {r.text[:100]}", "warn")
                return False
            except Exception as e:
                self._log(f"Loi enroll: {e}", "error")
                return False
        return False

    def _complete_video(self, quest: dict):
        name = get_quest_name(quest)
        qid = quest["id"]
        seconds_needed = get_seconds_needed(quest)
        seconds_done = get_seconds_done(quest)
        enrolled_at_str = get_enrolled_at(quest)

        if enrolled_at_str:
            enrolled_ts = datetime.fromisoformat(enrolled_at_str.replace("Z", "+00:00")).timestamp()
        else:
            enrolled_ts = time.time()

        self._log(f"Video: {name} ({seconds_done:.0f}/{seconds_needed}s)", "info")

        max_future = 10
        speed = 7
        interval = 1

        while seconds_done < seconds_needed and not self._stop.is_set():
            max_allowed = (time.time() - enrolled_ts) + max_future
            diff = max_allowed - seconds_done
            timestamp = seconds_done + speed

            if diff >= speed:
                try:
                    r = self._api.post(f"/quests/{qid}/video-progress", {
                        "timestamp": min(seconds_needed, timestamp + random.random())
                    })
                    if r.status_code == 200:
                        body = r.json()
                        if body.get("completed_at"):
                            self._stats["quests_completed"] += 1
                            self._log(f"Hoan thanh: {name}", "ok")
                            database.log_quest(self._get_token_id(), name, qid, "WATCH_VIDEO", "completed", "success")
                            return
                        seconds_done = min(seconds_needed, timestamp)
                        self._log(f"  [{name}] {seconds_done:.0f}/{seconds_needed}s", "progress")
                    elif r.status_code == 429:
                        retry_after = r.json().get("retry_after", 5)
                        self._log(f"Rate limited – cho {retry_after + 1}s", "warn")
                        time.sleep(retry_after + 1)
                        continue
                    else:
                        self._log(f"Video progress loi ({r.status_code}): {r.text[:200]}", "warn")
                except Exception as e:
                    self._log(f"Loi video progress: {e}", "error")

            if timestamp >= seconds_needed:
                break
            time.sleep(interval)

        try:
            self._api.post(f"/quests/{qid}/video-progress", {"timestamp": seconds_needed})
        except Exception:
            pass
        self._stats["quests_completed"] += 1
        self._log(f"Hoan thanh: {name}", "ok")
        database.log_quest(self._get_token_id(), name, qid, "WATCH_VIDEO", "completed", "success")

    def _complete_heartbeat(self, quest: dict):
        name = get_quest_name(quest)
        qid = quest["id"]
        task_type = get_task_type(quest)
        seconds_needed = get_seconds_needed(quest)
        seconds_done = get_seconds_done(quest)

        remaining = max(0, seconds_needed - seconds_done)
        self._log(f"{task_type}: {name} (~{remaining // 60} phut con lai)", "info")

        pid = random.randint(1000, 30000)

        while seconds_done < seconds_needed and not self._stop.is_set():
            try:
                r = self._api.post(f"/quests/{qid}/heartbeat", {
                    "stream_key": f"call:0:{pid}",
                    "terminal": False,
                })

                if r.status_code == 200:
                    body = r.json()
                    progress_data = body.get("progress", {})
                    if progress_data and task_type in progress_data:
                        seconds_done = progress_data[task_type].get("value", seconds_done)
                    self._log(f"  [{name}] {seconds_done:.0f}/{seconds_needed}s", "progress")

                    if body.get("completed_at") or seconds_done >= seconds_needed:
                        self._stats["quests_completed"] += 1
                        self._log(f"Hoan thanh: {name}", "ok")
                        database.log_quest(self._get_token_id(), name, qid, task_type or "", "completed", "success")
                        return

                elif r.status_code == 429:
                    retry_after = r.json().get("retry_after", 10)
                    self._log(f"Rate limited – cho {retry_after + 1}s", "warn")
                    time.sleep(retry_after + 1)
                    continue
                else:
                    self._log(f"Heartbeat loi ({r.status_code}): {r.text[:200]}", "warn")

            except Exception as e:
                self._log(f"Loi heartbeat: {e}", "error")

            time.sleep(HEARTBEAT_INTERVAL)

        try:
            self._api.post(f"/quests/{qid}/heartbeat", {
                "stream_key": f"call:0:{pid}",
                "terminal": True,
            })
        except Exception:
            pass
        self._stats["quests_completed"] += 1
        self._log(f"Hoan thanh: {name}", "ok")
        database.log_quest(self._get_token_id(), name, qid, task_type or "", "completed", "success")

    def _complete_activity(self, quest: dict):
        name = get_quest_name(quest)
        qid = quest["id"]
        seconds_needed = get_seconds_needed(quest)
        seconds_done = get_seconds_done(quest)

        remaining = max(0, seconds_needed - seconds_done)
        self._log(f"Activity: {name} (~{remaining // 60} phut con lai)", "info")

        stream_key = "call:0:1"

        while seconds_done < seconds_needed and not self._stop.is_set():
            try:
                r = self._api.post(f"/quests/{qid}/heartbeat", {
                    "stream_key": stream_key,
                    "terminal": False,
                })

                if r.status_code == 200:
                    body = r.json()
                    progress_data = body.get("progress", {})
                    if progress_data and "PLAY_ACTIVITY" in progress_data:
                        seconds_done = progress_data["PLAY_ACTIVITY"].get("value", seconds_done)
                    self._log(f"  [{name}] {seconds_done:.0f}/{seconds_needed}s", "progress")

                    if body.get("completed_at") or seconds_done >= seconds_needed:
                        self._stats["quests_completed"] += 1
                        self._log(f"Hoan thanh: {name}", "ok")
                        database.log_quest(self._get_token_id(), name, qid, "PLAY_ACTIVITY", "completed", "success")
                        return

                elif r.status_code == 429:
                    retry_after = r.json().get("retry_after", 10)
                    self._log(f"Rate limited – cho {retry_after + 1}s", "warn")
                    time.sleep(retry_after + 1)
                    continue
                else:
                    self._log(f"Activity heartbeat loi ({r.status_code}): {r.text[:200]}", "warn")

            except Exception as e:
                self._log(f"Loi activity: {e}", "error")

            time.sleep(HEARTBEAT_INTERVAL)

        try:
            self._api.post(f"/quests/{qid}/heartbeat", {
                "stream_key": stream_key,
                "terminal": True,
            })
        except Exception:
            pass
        self._stats["quests_completed"] += 1
        self._log(f"Hoan thanh: {name}", "ok")
        database.log_quest(self._get_token_id(), name, qid, "PLAY_ACTIVITY", "completed", "success")

    def _process_quest(self, quest: dict):
        qid = quest.get("id")
        name = get_quest_name(quest)
        task_type = get_task_type(quest)
        if not task_type:
            self._log(f'"{name}" – task khong ho tro, bo qua', "warn")
            return
        if qid in self._completed_ids:
            return
        if self._forced_stop:
            self._log(f'Dung thu cong – bo qua quest: {name}', "warn")
            return
        self._log(f"━━━ Bat dau: {name} (task: {task_type}) ━━━", "info")
        if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
            self._complete_video(quest)
        elif task_type in ("PLAY_ON_DESKTOP", "STREAM_ON_DESKTOP"):
            self._complete_heartbeat(quest)
        elif task_type == "PLAY_ACTIVITY":
            self._complete_activity(quest)
        self._completed_ids.add(qid)

    def run(self):
        self._running = True
        self._last_status = "running"
        self._stats["start_time"] = time.time()
        self._log("Worker khoi dong", "info")

        self._fetch_build()
        database.update_account_status(self.user_id, "running")
        self._session_id = database.start_session(self._get_token_id())
        self._log(f"Session #{self._session_id} started", "ok")

        cycle = 0
        stop_reason = "manual"
        while not self._stop.is_set():
            cycle += 1
            self._stats["cycles_run"] += 1
            self._status_msg = f"Quet lan #{cycle}"
            self._log(f"── Quet lan #{cycle} ──", "info")

            quests = self._fetch_quests()
            total = len(quests)
            had_new_quests = False

            if quests:
                enrolled_count = sum(1 for q in quests if is_enrolled(q))
                completed_count = sum(1 for q in quests if is_completed(q))
                completable_count = sum(1 for q in quests if is_completable(q))
                self._log(
                    f"Tong: {total} | Enrolled: {enrolled_count} | "
                    f"Completed: {completed_count} | Completable: {completable_count}", "info"
                )
                if self.auto_accept:
                    unaccepted = [q for q in quests
                                  if not is_enrolled(q) and not is_completed(q) and is_completable(q)]
                    if unaccepted:
                        self._log(f"Tu dong nhan {len(unaccepted)} quest...", "info")
                        for q in unaccepted:
                            self._enroll_quest(q)
                            time.sleep(3)
                            had_new_quests = True
                        quests = self._fetch_quests()

                actionable = [
                    q for q in quests
                    if is_enrolled(q) and not is_completed(q) and is_completable(q)
                    and q.get("id") not in self._completed_ids
                ]
                if actionable:
                    self._log(f"{len(actionable)} quest(s) can hoan thanh:", "info")
                    for q in actionable:
                        if self._stop.is_set():
                            break
                        self._process_quest(q)
                        had_new_quests = True
                else:
                    self._log("Khong co quest can hoan thanh", "info")
            else:
                self._log("Khong co quest nao, tiep tuc quet...", "info")

            if had_new_quests:
                self._cycles_without_new_quest = 0
                self._stats["last_new_quest_at"] = datetime.now().isoformat()
            else:
                self._cycles_without_new_quest += 1
                self._log(f"Cycles khong co quest moi: {self._cycles_without_new_quest}/{self._max_cycles_no_quest}", "progress")

            if self._cycles_without_new_quest >= self._max_cycles_no_quest:
                self._log(f"Khong co quest moi sau {self._max_cycles_no_quest} lan quet - tu dong dung!", "warn")
                stop_reason = "no_new_quests"
                break

            self._log(f"Stats: {self.get_stats_summary()}", "info")

            for _ in range(self.poll_interval):
                if self._stop.is_set():
                    break
                time.sleep(1)

        if self._stats["start_time"]:
            self._stats["runtime_seconds"] = int(time.time() - self._stats["start_time"])

        self._running = False
        self._last_status = "stopped"
        self._status_msg = "Da dung"

        if self._forced_stop:
            quests_check = self._fetch_quests()
            enrolled_left = [q for q in quests_check if is_enrolled(q) and not is_completed(q)]
            if enrolled_left:
                stop_reason = "manual_skip_quests"
                for q in enrolled_left:
                    name = get_quest_name(q)
                    qid = q.get("id")
                    self._log(f'Bo qua quest: {name} (da nhan nhung chua hoan thanh)', "warn")
                    database.log_quest(self._get_token_id(), name, qid, get_task_type(q) or "", "skipped", "stopped_by_user")

        if self._session_id:
            database.stop_session(self._session_id, stop_reason)
        database.update_account_status(self.user_id, "offline")

        self._unregister()
        self._log(f"=== FINAL STATS ===", "info")
        self._log(f"Completed: {self._stats['quests_completed']} quests", "info")
        self._log(f"Enrolled: {self._stats['quests_enrolled']} quests", "info")
        self._log(f"Cycles: {self._stats['cycles_run']}", "info")
        elapsed = self._stats["runtime_seconds"]
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self._log(f"Runtime: {hours}h {minutes}m {seconds}s", "info")
        self._log(f"Stop reason: {stop_reason}", "info")
        self._log("Worker da dung", "info")

    def _get_token_id(self) -> int:
        for acc in database.get_all_accounts():
            if acc.get("user_id") == self.user_id:
                return acc.get("id", 1)
        return 1

    def stop(self):
        self._forced_stop = True
        self._stop.set()

    def _unregister(self):
        with _worker_lock:
            if self.user_id in _active_workers:
                del _active_workers[self.user_id]


# ── Global worker registry ────────────────────────────────────────────────────

_worker_lock = threading.Lock()
_active_workers: dict[str, QuestWorker] = {}


def start_worker(token: str, user_id: str, username: str,
                 poll_interval: int = 60, auto_accept: bool = True,
                 max_cycles_no_quest: int = 30) -> QuestWorker:
    stop_worker(user_id)
    ev = threading.Event()
    w = QuestWorker(token, user_id, username, poll_interval, auto_accept, ev, max_cycles_no_quest)
    with _worker_lock:
        _active_workers[user_id] = w
    w.start()
    return w


def stop_worker(user_id: str):
    with _worker_lock:
        if user_id not in _active_workers:
            return
        w = _active_workers[user_id]
        w.stop()
        del _active_workers[user_id]
    w.join(timeout=10)


def get_worker(user_id: str) -> Optional[QuestWorker]:
    return _active_workers.get(user_id)


def get_all_workers() -> dict:
    return dict(_active_workers)


def get_running_accounts() -> list:
    with _worker_lock:
        return [
            {
                "user_id": uid, 
                "username": w.username, 
                "status": w.status,
                "message": w.status_message, 
                "running": w.is_running,
                "stats": w.stats,
            }
            for uid, w in _active_workers.items()
        ]
