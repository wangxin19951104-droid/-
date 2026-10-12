# -*- coding: utf-8 -*-
"""急急。选一位导演，由这位导演写出 Seedance 提示词。不提交成片。"""

import base64
import copy
import hashlib
import os
import jiji_core as core
import jiji_creation as creation
import jiji_media as media
from jiji_intelligence import Intelligence
from jiji_workflow import Workflow
import contextvars
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT
WEB = ROOT / "web" / "index.html"
CONFIG = ROOT / "config.json"
START_CONFIG = core.read_json(CONFIG, {})
# 0.0.0.0 仅用于监听所有网卡，浏览器请使用下方打印的实际地址。
BIND = str(os.environ.get("JIJI_BIND") or START_CONFIG.get("bind") or "0.0.0.0").strip() or "0.0.0.0"
LOCAL = "127.0.0.1"
PORT = int(os.environ.get("JIJI_PORT") or START_CONFIG.get("port") or 8765)
SCRIPT_LIMIT = 40000
CACHE_ROOT = Path(os.environ.get("JIJI_CACHE_ROOT") or START_CONFIG.get("cache_root") or r"W:\AIGC缓存")
PROJECTS_DIR = CACHE_ROOT / "projects"
OUTPUT_DIR = CACHE_ROOT / "output"
ASSET_ASPECT = "21:9"
INDEX_LOCK = threading.RLock()
WORKS = {}
WORKS_LOCK = threading.Lock()
HOLD = {}
HOLD_LOCK = threading.Lock()
HOLD_SECONDS = 90
ACTIVE = contextvars.ContextVar("desk_work", default=None)


class Work:
    def __init__(self):
        self.script = {"name": "", "text": ""}
        self.scenes = []
        self.assets = []
        self.job = {"phase": "idle", "jobs": [], "film": "", "error": ""}
        self.current_id = {"id": ""}
        self.refs = []
        self.mode = {"image": "banana", "video": "seedance"}
        self.chat = {
            "director_id": "",
            "director_name": "",
            "step": "director",
            "ratio": "",
            "resolution": "",
            "messages": [],
        }
        self.thinking = {"on": False, "text": ""}
        self.writing = {"on": False}
        self.model_lock = threading.Lock()
        self.drawing = {"on": False, "phase": "", "index": 0, "total": 0, "kind": "", "name": ""}
        self.task = {"state": "idle", "kind": "", "label": "", "mark": ""}
        self.task_lock = threading.Lock()
        self.task_go = threading.Event()
        self.task_go.set()
        self.task_stop = threading.Event()
        self.live_io = {"close": None}
        self.style = {"query": "", "note": "", "file": "", "files": [], "uploads": [], "confirmed": False, "choices": [], "page": 1, "locked_to": ""}
        self.style_busy = {"on": False}
        self.prompt_from = {"text": ""}
        self.session_lock = threading.RLock()
        self.intelligence = core.default_intelligence()
        self.loaded = False


class TaskStopped(RuntimeError):
    pass


class TaskHeld(RuntimeError):
    pass


def active():
    work = ACTIVE.get()
    return work if work is not None else BENCH


def spawn(target):
    work = active()

    def run():
        ACTIVE.set(work)
        target()

    threading.Thread(target=run, daemon=True).start()


class DictView:
    def __init__(self, field):
        self.field = field

    def raw(self):
        return getattr(active(), self.field)

    def get(self, key, default=None):
        return self.raw().get(key, default)

    def __getitem__(self, key):
        return self.raw()[key]

    def __setitem__(self, key, value):
        self.raw()[key] = value

    def __contains__(self, key):
        return key in self.raw()

    def __iter__(self):
        return iter(self.raw())

    def __len__(self):
        return len(self.raw())

    def __bool__(self):
        return bool(self.raw())

    def update(self, other=None, **kwargs):
        if other:
            self.raw().update(other)
        if kwargs:
            self.raw().update(kwargs)

    def setdefault(self, key, default=None):
        return self.raw().setdefault(key, default)

    def keys(self):
        return self.raw().keys()

    def items(self):
        return self.raw().items()

    def values(self):
        return self.raw().values()

    def pop(self, key, *args):
        return self.raw().pop(key, *args)

    def clear(self):
        self.raw().clear()

    def copy(self):
        return self.raw().copy()


class ListView:
    def __init__(self, field):
        self.field = field

    def raw(self):
        return getattr(active(), self.field)

    def clear(self):
        self.raw().clear()

    def extend(self, items):
        self.raw().extend(items)

    def append(self, item):
        self.raw().append(item)

    def remove(self, item):
        self.raw().remove(item)

    def pop(self, index=-1):
        return self.raw().pop(index)

    def insert(self, index, item):
        self.raw().insert(index, item)

    def __iter__(self):
        return iter(list(self.raw()))

    def __len__(self):
        return len(self.raw())

    def __getitem__(self, index):
        return self.raw()[index]

    def __setitem__(self, index, value):
        self.raw()[index] = value

    def __delitem__(self, index):
        del self.raw()[index]

    def __bool__(self):
        return bool(self.raw())

    def __contains__(self, item):
        return item in self.raw()


class LockView:
    def __init__(self, field):
        self.field = field

    def _lock(self):
        return getattr(active(), self.field)

    def __enter__(self):
        return self._lock().__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._lock().__exit__(exc_type, exc, tb)

    def acquire(self, *args, **kwargs):
        return self._lock().acquire(*args, **kwargs)

    def release(self):
        return self._lock().release()


class EventView:
    def __init__(self, field):
        self.field = field

    def _event(self):
        return getattr(active(), self.field)

    def set(self):
        self._event().set()

    def clear(self):
        self._event().clear()

    def wait(self, timeout=None):
        return self._event().wait(timeout)

    def is_set(self):
        return self._event().is_set()


def json_default(obj):
    raw = getattr(obj, "raw", None)
    if callable(raw):
        return raw()
    raise TypeError("不能序列化")


BENCH = Work()
SCRIPT = DictView("script")
SCENES = ListView("scenes")
ASSETS = ListView("assets")
JOB = DictView("job")
CURRENT_ID = DictView("current_id")
REFS = ListView("refs")
MODE = DictView("mode")
CHAT = DictView("chat")
THINKING = DictView("thinking")
WRITING = DictView("writing")
MODEL_LOCK = LockView("model_lock")
DRAWING = DictView("drawing")
TASK = DictView("task")
TASK_LOCK = LockView("task_lock")
TASK_GO = EventView("task_go")
TASK_STOP = EventView("task_stop")
LIVE_IO = DictView("live_io")
STYLE = DictView("style")
STYLE_BUSY = DictView("style_busy")
PROMPT_FROM = DictView("prompt_from")
SESSION_LOCK = LockView("session_lock")
INTELLIGENCE = Intelligence(sys.modules[__name__])
WORKFLOW = Workflow(sys.modules[__name__])


def session_public():
    INTELLIGENCE.identify()
    return {
        "intelligence": active().intelligence,
        "skill": INTELLIGENCE.skill_status(),
        "director_id": CHAT.get("director_id") or "",
        "director_name": CHAT.get("director_name") or "",
        "step": CHAT.get("step") or "director",
        "ratio": CHAT.get("ratio") or "",
        "resolution": CHAT.get("resolution") or "",
        "messages": CHAT.get("messages") or [],
        "script_name": SCRIPT.get("name") or "",
        "script_chars": len(SCRIPT.get("text") or ""),
        "script_preview": (SCRIPT.get("text") or "")[:1600],
        "scenes": SCENES,
        "assets": ASSETS,
        "refs": REFS,
        "project_id": CURRENT_ID.get("id") or "",
        "image_model": MODE.get("image") or "banana",
        "video_model": MODE.get("video") or "seedance",
        "seconds_choice": MODE.get("seconds") or "auto",
        "thinking": bool(THINKING.get("on")),
        "thinking_text": THINKING.get("text") or "",
        "drawing": {
            "on": bool(DRAWING.get("on")),
            "phase": DRAWING.get("phase") or "",
            "index": DRAWING.get("index") or 0,
            "total": DRAWING.get("total") or 0,
            "kind": DRAWING.get("kind") or "",
            "name": DRAWING.get("name") or "",
        },
        "task": task_public(),
        "style": style_public(),
        "prompt_from": PROMPT_FROM.get("text") or "",
        "job": {
            "phase": JOB.get("phase") or "idle",
            "film": JOB.get("film") or "",
            "error": JOB.get("error") or "",
            "started": JOB.get("started") or 0,
            "jobs": [
                {
                    "place": item.get("place") or "",
                    "seconds": item.get("seconds") or 0,
                    "status": item.get("status") or "",
                    "scene_id": item.get("scene_id"),
                    "fingerprint": item.get("fingerprint"),
                    "prompt_id": item.get("prompt_id"),
                    "error": item.get("error"),
                }
                for item in (JOB.get("jobs") or [])
            ],
        },
    }


def project_dir():
    pid = CURRENT_ID.get("id") or ""
    if not pid:
        raise RuntimeError("先打开一个项目。")
    return PROJECTS_DIR / pid


def session_file():
    return project_dir() / "session.json"


def lib():
    path = project_dir() / "library"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ref_dir():
    path = project_dir() / "refs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_index():
    data = core.read_json(PROJECTS_DIR / "index.json", [])
    return data if isinstance(data, list) else []


def write_index_unlocked(rows):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    core.atomic_write(PROJECTS_DIR / "index.json", json.dumps(rows, ensure_ascii=False, indent=2))
    pid = CURRENT_ID.get("id") or ""
    if pid:
        core.atomic_write(PROJECTS_DIR / "current.txt", pid)


def write_index(rows):
    with INDEX_LOCK:
        write_index_unlocked(rows)


def blank_work():
    active().intelligence = core.default_intelligence()
    SCRIPT["name"] = ""
    SCRIPT["text"] = ""
    SCENES.clear()
    ASSETS.clear()
    REFS.clear()
    JOB.update({"phase": "idle", "jobs": [], "film": "", "error": ""})
    CHAT.update({
        "director_id": "",
        "director_name": "",
        "step": "director",
        "ratio": "",
        "resolution": "",
        "messages": [],
    })
    STYLE.update({"query": "", "note": "", "file": "", "files": [], "uploads": [], "confirmed": False, "choices": [], "page": 1, "locked_to": ""})
    PROMPT_FROM["text"] = ""
    MODE.update({"image": "banana", "video": "seedance", "seconds": "auto"})


def save_session():
    with SESSION_LOCK:
        _save_session()


def _save_session():
    pid = CURRENT_ID.get("id") or ""
    if not pid:
        return
    with INDEX_LOCK:
        if not any(row.get("id") == pid for row in read_index()):
            return
    folder = project_dir()
    folder.mkdir(parents=True, exist_ok=True)
    payload = session_public()
    payload["messages"] = [dict(item) for item in (CHAT.get("messages") or [])]
    payload["scenes"] = [dict(item) for item in SCENES]
    payload["assets"] = [dict(item) for item in ASSETS]
    payload["refs"] = [dict(item) for item in REFS]
    payload["script_text"] = SCRIPT.get("text") or ""
    payload["job"] = {
        "phase": JOB.get("phase") or "idle",
        "jobs": JOB.get("jobs") or [],
        "film": JOB.get("film") or "",
        "error": JOB.get("error") or "",
        "started": JOB.get("started") or 0,
    }
    core.atomic_write(session_file(), json.dumps(payload, ensure_ascii=False, default=json_default))
    with INDEX_LOCK:
        rows = read_index()
        found = False
        for row in rows:
            if row.get("id") == pid:
                row["script"] = SCRIPT.get("name") or ""
                found = True
        if not found:
            return
        write_index_unlocked(rows)


def load_session():
    path = session_file()
    if not path.is_file() and not path.with_name(path.name + ".bak").is_file():
        blank_work()
        return
    try:
        data = core.read_json(path, {})
    except (OSError, json.JSONDecodeError):
        blank_work()
        return
    if not isinstance(data, dict):
        blank_work()
        return
    active().intelligence = {**core.default_intelligence(), **(data.get("intelligence") if isinstance(data.get("intelligence"), dict) else {})}
    for video in active().intelligence.get("source_videos", []):
        if video.get("status") == "analyzing":
            video.update({"status":"error","error":"程序重启打断了解析，可以重新解析。"})
    SCRIPT["name"] = str(data.get("script_name") or "")
    SCRIPT["text"] = str(data.get("script_text") or "")
    SCENES.clear()
    SCENES.extend(data.get("scenes") or [])
    ASSETS.clear()
    ASSETS.extend(data.get("assets") or [])
    REFS.clear()
    REFS.extend(data.get("refs") or [])
    job = data.get("job") if isinstance(data.get("job"), dict) else {}
    JOB.update({
        "phase": job.get("phase") or "idle",
        "jobs": job.get("jobs") or [],
        "film": job.get("film") or "",
        "error": job.get("error") or "",
    })
    try:
        JOB["started"] = float(job.get("started") or 0)
    except (TypeError, ValueError):
        JOB["started"] = 0
    for job in JOB["jobs"]:
        if isinstance(job, dict) and job.get("status") == "held":
            job["status"] = "queued"
    for key in ("director_id", "director_name", "step", "ratio", "resolution"):
        CHAT[key] = str(data.get(key) or "")
    if not CHAT["step"]:
        CHAT["step"] = "director"
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    CHAT["messages"] = messages
    style = data.get("style") if isinstance(data.get("style"), dict) else {}
    choices = []
    for item in style.get("choices") or []:
        if isinstance(item, dict) and item.get("file"):
            choices.append({"file": str(item.get("file")), "title": str(item.get("title") or "")[:80]})
    try:
        page = int(style.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    STYLE.update({
        "query": str(style.get("query") or ""),
        "note": str(style.get("note") or ""),
        "file": str(style.get("file") or ""),
        "confirmed": bool(style.get("confirmed")),
        "locked_to": str(style.get("locked_to") or ""),
        "files": [str(name) for name in (style.get("files") or []) if name][:8],
        "uploads": [
            {"file": str(item.get("file")), "title": str(item.get("title") or "")[:80]}
            for item in (style.get("uploads") or [])
            if isinstance(item, dict) and item.get("file")
        ][:8],
        "choices": choices,
        "page": page if page > 0 else 1,
    })
    PROMPT_FROM["text"] = str(data.get("prompt_from") or "")
    image_model = str(data.get("image_model") or "banana")
    video_model = str(data.get("video_model") or "seedance")
    MODE["image"] = image_model if image_model in SHEET_MODELS else "banana"
    MODE["video"] = video_model if video_model in {"seedance", "h3"} else "seedance"
    MODE["seconds"] = normalize_seconds_choice(data.get("seconds_choice"))
    relink_assets()
    INTELLIGENCE.identify()
    for saved_job in JOB.get("jobs") or []:
        if saved_job.get("status") in {"submitting", "reserved"}:
            saved_job["status"] = "unknown"
            JOB["phase"] = "error"
            JOB["error"] = "上次提交结果未知，请先核对队列，不会自动重发。"


def work_for(pid):
    pid = str(pid or "").strip()
    with WORKS_LOCK:
        work = WORKS.get(pid)
        if work is None:
            work = Work()
            work.current_id["id"] = pid
            WORKS[pid] = work
    token = ACTIVE.set(work)
    try:
        with work.session_lock:
            if not work.loaded:
                load_session()
                work.loaded = True
    finally:
        ACTIVE.reset(token)
    return work


def claim(pid, client):
    client = str(client or "").strip()
    if not client:
        raise RuntimeError("刷新一次，这一页才能单独使用。")
    now = time.time()
    with HOLD_LOCK:
        row = HOLD.get(pid)
        work = WORKS.get(pid)
        busy = bool(work is not None and (work.task.get("state") or "") in {"running", "paused", "stopping"})
        if row and row.get("client") != client and (now - float(row.get("seen") or 0) < HOLD_SECONDS or busy):
            raise RuntimeError("这个项目正有人在用。换一个项目。")
        HOLD[pid] = {"client": client, "seen": now}


def release_other(client, keep):
    client = str(client or "").strip()
    if not client:
        return
    with HOLD_LOCK:
        for pid, row in list(HOLD.items()):
            if pid == keep or row.get("client") != client:
                continue
            work = WORKS.get(pid)
            if work is not None and (work.task.get("state") or "") in {"running", "paused", "stopping"}:
                continue
            HOLD.pop(pid, None)


def open_project(pid, client=""):
    rows = read_index()
    if not any(row.get("id") == pid for row in rows):
        raise RuntimeError("没有这个项目。")
    claim(pid, client)
    work = work_for(pid)
    ACTIVE.set(work)
    release_other(client, pid)


def delete_project(pid, client=""):
    pid = str(pid or "").strip()
    if not re.fullmatch(r"[\w\-]+", pid):
        raise RuntimeError("这个项目删不掉。")
    rows = read_index()
    if not any(row.get("id") == pid for row in rows):
        raise RuntimeError("没有这个项目。")
    folder = (PROJECTS_DIR / pid).resolve()
    if folder.parent != PROJECTS_DIR.resolve():
        raise RuntimeError("这个项目删不掉。")
    claim(pid, client)
    with INDEX_LOCK:
        rows = [row for row in read_index() if row.get("id") != pid]
        write_index_unlocked(rows)
    with WORKS_LOCK:
        WORKS.pop(pid, None)
    with HOLD_LOCK:
        HOLD.pop(pid, None)
    if ACTIVE.get() is not None and CURRENT_ID.get("id") == pid:
        ACTIVE.set(BENCH)
    if folder.is_dir():
        shutil.rmtree(folder)
    return projects_public()


def create_project(name, client=""):
    title = str(name or "").strip() or "未命名"
    pid = time.strftime("%Y%m%d%H%M%S") + f"{int((time.time() % 1) * 1000):03d}"
    with INDEX_LOCK:
        rows = read_index()
        while any(row.get("id") == pid for row in rows):
            pid += "x"
        rows.insert(0, {"id": pid, "name": title, "script": ""})
        write_index_unlocked(rows)
    work = Work()
    work.current_id["id"] = pid
    work.loaded = True
    with WORKS_LOCK:
        WORKS[pid] = work
    ACTIVE.set(work)
    project_dir().mkdir(parents=True, exist_ok=True)
    claim(pid, client)
    release_other(client, pid)
    save_session()
    return {"id": pid, "name": title}


def ensure_projects():
    if not CACHE_ROOT.drive or not Path(CACHE_ROOT.drive + "\\").exists():
        raise RuntimeError("缓存目录无法访问：" + str(CACHE_ROOT) + "。请在config.json设置cache_root。")
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    local = ROOT / "projects"
    if local.is_dir() and (local / "index.json").is_file() and not (PROJECTS_DIR / "index.json").is_file():
        shutil.copytree(local, PROJECTS_DIR, dirs_exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = read_index()
    if not rows:
        pid = "default"
        folder = PROJECTS_DIR / pid
        folder.mkdir(parents=True, exist_ok=True)
        old_session = ROOT / "session.json"
        target = folder / "session.json"
        if old_session.is_file() and not target.is_file():
            shutil.copy(old_session, target)
        old_lib = ROOT / "library"
        dest = folder / "library"
        dest.mkdir(parents=True, exist_ok=True)
        if old_lib.is_dir():
            for item in old_lib.iterdir():
                if item.is_file() and not (dest / item.name).exists():
                    shutil.copy(item, dest / item.name)
        rows = [{"id": pid, "name": "默认项目", "script": ""}]
        write_index(rows)
    pointer = PROJECTS_DIR / "current.txt"
    chosen = rows[0]["id"]
    if pointer.is_file():
        want = pointer.read_text(encoding="utf-8").strip()
        if any(row.get("id") == want for row in rows):
            chosen = want
    work_for(chosen)


def auto_cover(pid):
    pid = str(pid or "").strip()
    if not re.fullmatch(r"[\w\-]+", pid):
        return None
    folder = (PROJECTS_DIR / pid).resolve()
    if folder.parent != PROJECTS_DIR.resolve() or not folder.is_dir():
        return None
    suffixes = {".png", ".jpg", ".jpeg", ".webp"}

    def images(directory):
        if not directory.is_dir():
            return []
        return [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in suffixes]

    def rank(path):
        name = path.name
        if name.startswith("人物"):
            group = 0
        elif name.startswith("道具"):
            group = 1
        elif name.startswith("场景"):
            group = 2
        else:
            group = 3
        number = re.search(r"_(\d+)_", name)
        index = int(number.group(1)) if number else 9999
        return (group, index, name)

    library = images(folder / "library")
    if library:
        return sorted(library, key=rank)[0]
    refs = images(folder / "refs")
    if refs:
        return sorted(refs, key=lambda path: path.name)[0]
    return None


def projects_public():
    rows = []
    for row in read_index():
        item = dict(row)
        path = auto_cover(item.get("id"))
        item["cover"] = ""
        if path:
            item["cover"] = "/covers/" + item["id"] + "?v=" + str(int(path.stat().st_mtime))
        rows.append(item)
    return {
        "current": CURRENT_ID.get("id") or "",
        "projects": rows,
    }


def update_chat(data):
    for key in ("director_id", "director_name", "step", "ratio", "resolution"):
        if key in data:
            CHAT[key] = str(data.get(key) or "")
    if "video_model" in data and data['video_model'] in {'seedance','h3'}:
        engine = data['video_model']
        if engine != MODE.get('video'):
            if TASK.get('state') != 'idle': raise RuntimeError('当前任务结束后才能切换视频模型。')
            for scene in SCENES:
                scene.pop('confirmation', None)
                if scene.get('prompt'): scene['needs_rewrite'] = True
            active().intelligence['director_drafts'] = []
        MODE['video'] = engine
    if "image_model" in data and data['image_model'] in {'banana','seedream','image25'}:
        MODE['image'] = data['image_model']
    if "seconds_choice" in data:
        MODE["seconds"] = normalize_seconds_choice(data["seconds_choice"])
    if "messages" in data and not THINKING.get("on"):
        CHAT["messages"] = core.merge_history(CHAT.get("messages") or [], data.get("messages"))
    save_session()

SCALES = ("航拍远", "远", "中", "中近", "近", "近肩", "特", "腰特", "低")
BAD_SCALES = ("特写", "全景", "近景", "中景", "远景", "大特写", "中近景")

SKILLS = ROOT / "skills"
DIRECTORS = [
    ("product-ad", "广告", "一件使用，停在要认出的那一面。", SKILLS / "广告.md"),
    ("live-commerce", "电商", "一次一步。口播和画面分开。", SKILLS / "电商.md"),
    ("automotive", "汽车", "同一辆车，只走一条线。", SKILLS / "汽车.md"),
    ("drama", "短剧", "一场一个画面。对白留出反应。", SKILLS / "短剧.md"),
]


def project_key_for(base_url):
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from api_keys import load_keys
    keys = load_keys()
    host = base_url.lower()
    if "dashscope" in host:
        return keys.get("DASHSCOPE_API_KEY") or ""
    if "deepseek.com" in host:
        return keys.get("DEEPSEEK_API_KEY") or ""
    if "openrouter" in host:
        return keys.get("OPENROUTER_API_KEY") or ""
    if "volces.com" in host:
        return keys.get("ARK_API_KEY") or ""
    if "junflow.cn" in host:
        return keys.get("JUNFLOW_API_KEY") or ""
    return ""


def resolve_key(cfg):
    saved = str(cfg.get("api_key") or "").strip()
    if saved:
        return saved
    try:
        return project_key_for(cfg.get("base_url") or "")
    except Exception:
        return ""


def load_config():
    data = core.read_json(CONFIG, {})
    if not isinstance(data, dict):
        data = {}
    for key, value in {"base_url": "http://127.0.0.1:11434", "model": "qwen2.5:7b", "api_key": "", "comfy_url": "http://127.0.0.1:8188", "reasoning_effort": "xhigh"}.items():
        data.setdefault(key, value)
    if data.get("reasoning_effort") not in {"low", "medium", "high", "xhigh"}:
        data["reasoning_effort"] = "xhigh"
    return data


def save_config(data):
    current = load_config()
    current["base_url"] = str(data.get("base_url") or current["base_url"]).strip()
    current["model"] = str(data.get("model") or current["model"]).strip()
    if "api_key" in data and data["api_key"] != "******":
        current["api_key"] = str(data.get("api_key") or "")
    if data.get("comfy_url"):
        current["comfy_url"] = str(data["comfy_url"]).strip().rstrip("/")
    core.atomic_write(CONFIG, json.dumps(current, ensure_ascii=False, indent=2))
    return current


def director_by_id(director_id):
    for item in DIRECTORS:
        if item[0] == director_id:
            return item
    return None


def public_directors():
    rows = []
    for director_id, name, line, path in DIRECTORS:
        rows.append({
            "id": director_id,
            "name": name,
            "line": line,
            "ready": path.exists(),
        })
    return rows


def read_docx_text(raw):
    import zipfile
    from xml.etree import ElementTree as ET
    paragraph = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
    text_node = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    lines = []
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = ["word/document.xml"]
        names += [
            name for name in zf.namelist()
            if name.startswith("word/header") or name.startswith("word/footer")
        ]
        for name in names:
            if name not in zf.namelist():
                continue
            root = ET.fromstring(zf.read(name))
            for node in root.iter(paragraph):
                line = "".join((item.text or "") for item in node.iter(text_node)).strip()
                if line and line not in lines:
                    lines.append(line)
    return "\n".join(lines)


def read_script_bytes(name, raw):
    lower = name.lower()
    if lower.endswith(".docx"):
        return read_docx_text(raw)
    if lower.endswith((".xlsx", ".csv", ".tsv", ".xls")):
        from jiji_tables import read_table
        return read_table(name, raw, SCRIPT_LIMIT)
    if lower.endswith((".txt", ".md")):
        return raw.decode("utf-8-sig")
    raise ValueError("支持 .docx、.txt、.md、.xlsx、.csv、.tsv")


def store_script(name, raw):
    text = read_script_bytes(name, raw).strip()
    if not text:
        raise ValueError("这份文件里没有字")
    clipped = False
    if len(text) > SCRIPT_LIMIT:
        text = text[:SCRIPT_LIMIT]
        clipped = True
    SCRIPT["name"] = Path(name).name
    SCRIPT["text"] = text
    SCENES.clear()
    ASSETS.clear()
    JOB.update({"phase": "idle", "jobs": [], "film": "", "error": ""})
    save_session()
    return {"name": SCRIPT["name"], "chars": len(text), "clipped": clipped}


def scene_field(block, name):
    match = re.search(rf"^{name}[:：]\s*(.*)$", block, re.M)
    return match.group(1).strip() if match else ""


def split_scenes(text):
    scenes = []
    for match in re.finditer(r"<<<SCENE>>>(.*?)<<<END>>>", text, re.S):
        block = match.group(1)
        place = scene_field(block, "地点")
        who = scene_field(block, "画里有谁")
        remember = scene_field(block, "记住")
        if not (place or who or remember):
            continue
        seconds_raw = scene_field(block, "秒数")
        seconds_match = re.search(r"\d+", seconds_raw or "")
        seconds = int(seconds_match.group(0)) if seconds_match else 0
        episode_raw = scene_field(block, "集数")
        episode_match = re.search(r"\d+", episode_raw or "")
        episode = int(episode_match.group(0)) if episode_match else 1
        scenes.append({
            "episode": episode,
            "place": place,
            "who": who,
            "remember": remember,
            "seconds": seconds,
            "prompt": "",
            "settings": "",
            "warnings": [],
        })
    return scenes


def classify_prompt(director_id):
    item = director_by_id(director_id)
    if item is None or not item[3].exists():
        raise FileNotFoundError(director_id)
    skill = ""  # Shared Skill is injected by INTELLIGENCE.prepare.
    return f"""你是{item[1]}导演。这次只分场，不写提示词，不提交。

下面这份技能用来判断一场该不该切开。不要把整本剧本写成一条提示词。

{skill}

换地方，或观众要记住的那一件换了，才新开一场。同一地方、同一件要记住的事，不要拆碎。心理、旁白、作者判断不能单独成场。

资产和场次只能来自剧本正文。正文里没有的人、动物、物件不准写上。正文写鸭子，名称就写鸭子，不准改成小女孩或小孩。文件名不是剧情。正文不够，不要编一场。

每场给一个交给 Seedance 的秒数，整数，4 到 30。按这一场要发生的事来定，不要每场都写 15。剧本里写了集数就填集数，没有就写 1。

接着列出全剧要出的静帧，一张资产只出现一次。人物每种写一张。道具每种写一张。同一个地点只写一张。

只输出标记，按顺序：

<<<SCENE>>>
集数：
场次：
地点：
画里有谁：
记住：
秒数：
<<<END>>>

<<<ASSET>>>
种类：人物
名称：
画面：
<<<END>>>

种类只写人物、道具、场景。人物写要认出的长相和衣服，不要写背景。道具写那一件和要认出的那一面。场景写这个地点空着时的光和地面。记住这一行只写观众看得见的一件事。

剧本《{SCRIPT["name"]}》：

{SCRIPT["text"]}
"""


def classify_scenes(director_id):
    if not SCRIPT["text"]:
        raise RuntimeError("先上传剧本。")
    if assets_need_redraw():
        raise RuntimeError("现在的资产还是旧样子。先点生图，等重出后再分场。")
    if len(SCRIPT["text"]) < 40:
        raise RuntimeError("Word 里只读出了这些字，没有往下编：" + SCRIPT["text"])
    task_begin("write", "分场")
    try:
        return _classify_scenes(director_id)
    except TaskStopped:
        raise RuntimeError("已终止")
    finally:
        task_finish("write")


def _classify_scenes(director_id):
    raw = call_model([
        {"role": "system", "content": classify_prompt(director_id)},
        {"role": "user", "content": "按剧本把这场戏分好。"},
    ])
    task_gate()
    scenes = split_scenes(raw)
    assets = split_assets(raw)
    if not scenes:
        raise RuntimeError("这场没有分成场。剧本再传一次，或换一位导演。")
    SCENES.clear()
    SCENES.extend(scenes)
    ASSETS.clear()
    ASSETS.extend(assets)
    save_session()
    return {"scenes": scenes, "assets": assets}


def split_assets(text):
    rows = []
    for match in re.finditer(r"<<<ASSET>>>(.*?)<<<END>>>", text, re.S):
        block = match.group(1)
        kind = scene_field(block, "种类")
        if "人" in kind:
            kind = "人物"
        elif "景" in kind:
            kind = "场景"
        else:
            kind = "道具"
        name = scene_field(block, "名称") or kind
        picture = scene_field(block, "画面")
        if not picture:
            continue
        rows.append({"kind": kind, "name": name, "picture": picture, "file": ""})
    return rows


def asset_file(name):
    for asset in ASSETS:
        if (asset.get("name") or "") != name or not asset.get("file"):
            continue
        path = lib() / asset["file"]
        if path.is_file() and name in path.stem:
            return path
    return None


def bound_reference_files(name):
    INTELLIGENCE.identify()
    target = next((a for a in ASSETS if a.get("name") == name), None)
    ids = target.get("reference_ids") or [] if target else []
    return [lib() / a["file"] for a in ASSETS if a.get("id") in ids and a.get("file") and (lib() / a["file"]).is_file()]


def asset_picture(kind, picture):
    lead = {
        "人物": "纯白背景，同一个主体四视图：正面、左侧、背面、右侧。全身、服装一致；不加文字。",
        "场景": "画出这个地点的完整空间、地面与光线。不要白底、不要人物、不要文字。",
        "道具": "纯白背景只放这一件，最容易识别的一面朝向镜头；不加人手、文字和场景。",
    }.get(kind, "只画用户指定的主体。")
    if any(word in picture for word in ("关系图", "体型对比", "比例关系")):
        lead = "按要求画关系或比例，不拆成四视图；数量与主体必须来自项目设定，不加文字。"
    facts = "；".join(row["fact"] for row in active().intelligence["memory"])
    return lead + " 项目已确认要求：" + facts + "。" + picture


def is_status_bubble(text):
    raw = (text or "").strip()
    if not raw:
        return True
    if "提示词正文在下面" in raw or "上面是概述" in raw:
        return True
    head = raw[:24]
    marks = (
        "已按场提交",
        "风格定了",
        "提示词写好了",
        "资产图出完了",
        "没有新的要出",
        "这句没想完",
        "成片好了",
        "成片没有接上",
        "分好了。",
        "整支片子让观众记住",
        "观众先看见",
        "观众看见",
    )
    return any(head.startswith(mark) for mark in marks)


def usable_messages(messages):
    rows = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "director":
            role = "assistant"
        if role not in ("user", "assistant"):
            continue
        content = str(message.get("content") or "").strip()
        if not content or (role == "assistant" and is_status_bubble(content)):
            continue
        rows.append({"role": role, "content": content})
    return rows


def story_messages(messages):
    rows = usable_messages(messages)
    last_user = -1
    for index, message in enumerate(rows):
        if message["role"] == "user":
            last_user = index
    if last_user < 0:
        return rows
    kept = [message for message in rows[:last_user] if message["role"] == "user"]
    if len((rows[last_user].get("content") or "").strip()) <= 12:
        for index in range(last_user - 1, -1, -1):
            if rows[index]["role"] == "assistant":
                kept.append(rows[index])
                break
    kept.extend(rows[last_user:])
    plan = director_segment_plan(rows)
    if plan is not None and all(plan.get("content") != item.get("content") for item in kept):
        kept.insert(max(0, len(kept) - len(rows[last_user:])), plan)
    return kept


def segment_locked(messages=None):
    rows = usable_messages(messages if messages is not None else (CHAT.get("messages") or []))
    text = "\n".join(item.get("content") or "" for item in rows)
    return ("25" in text and "30" in text) and any(word in text for word in ("一段", "每段", "25–30", "25-30"))


def director_segment_plan(rows):
    for message in reversed(rows or []):
        if message.get("role") != "assistant":
            continue
        text = message.get("content") or ""
        if "第一段" in text and "第二段" in text and "25" in text and "30" in text:
            return message
    return None


def story_anchor(messages):
    for message in reversed(story_messages(messages)):
        if message["role"] == "user":
            return message["content"][:240]
    return ""


def relink_assets():
    folder = project_dir() / "library"
    if not folder.is_dir():
        return
    files = [
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    for asset in ASSETS:
        if asset.get("file") or asset.get("kind") == "音频":
            continue
        name = (asset.get("name") or "").strip()
        if not name:
            continue
        hits = [path for path in files if path.stem == name or path.stem.endswith("_" + name)]
        if len(hits) == 1:
            asset["file"] = hits[0].name


def talk_text(limit=16):
    lines = []
    chosen = story_messages(CHAT.get("messages") or [])[-limit:]
    last = len(chosen) - 1
    for index, message in enumerate(chosen):
        content = (message.get("content") or "").strip()
        if not content:
            continue
        cap = 8000 if index >= last - 1 else 1200
        if len(content) > cap:
            content = content[-cap:]
        role = "用户" if message.get("role") == "user" else "导演"
        lines.append(role + "：" + content)
    if SCRIPT.get("text"):
        lines.append("剧本《" + (SCRIPT.get("name") or "") + "》：" + SCRIPT["text"][:8000])
    return "\n\n".join(lines)


def assets_from_talk(director_id, only_changes=False):
    if director_by_id(director_id) is None:
        raise FileNotFoundError(director_id)
    body = talk_text()
    if len(body) < 10:
        raise RuntimeError("对话里还没有能出图的人、场景或道具。先说清要哪几张。")
    existing = ""
    if only_changes:
        lines = [
            f"{asset.get('kind')} {asset.get('name')}：{(asset.get('picture') or '').strip()}"
            for asset in ASSETS
            if asset.get("kind") != "音频" and asset.get("name")
        ]
        existing = (
            "已经有的资产，这次没被点名就不要输出：\n"
            + ("\n".join(lines) if lines else "还没有")
            + "\n\n导演这次点名要补的每一张都单独输出。同一只生物的另一种状态、另一张关系图，也是新的一张，不要并进旧名称。"
            + "名称用导演这次写的名字。这次最多再加 8 张，不受已经有的张数限制。导演这次没有点名要补的，才什么标记都不要写。"
        )
        system = f"""只根据导演刚刚点名要补的内容列出静帧。对话里没有的人、动物、物件不准加。

{existing}

只输出标记：

<<<ASSET>>>
种类：人物
名称：
画面：
<<<END>>>

种类只写人物、道具、场景。画面只锁要认出的长相、衣服或那一件东西。不要写白底，不要写四视图，不要写站姿。场景写这个地点空着时的光和地面。"""
    else:
        system = """只根据下面已经聊定的内容，列出要出的静帧。对话里没有的人、动物、物件不准加。导演已经点名的那几张，按那几张写，不要再加一套。

每种人物一张，每种道具一张，每个地点一张。最多 8 张。

只输出标记：

<<<ASSET>>>
种类：人物
名称：
画面：
<<<END>>>

种类只写人物、道具、场景。画面只锁要认出的长相、衣服或那一件东西。不要写白底，不要写四视图，不要写站姿。场景写这个地点空着时的光和地面。"""
    raw = call_model([
        {"role": "system", "content": system},
        {"role": "user", "content": body},
    ])
    return split_assets(raw)[:8]


def talk_from_messages(messages, limit=30):
    lines = []
    chosen = list(messages or [])[-limit:]
    last = len(chosen) - 1
    for index, message in enumerate(chosen):
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        cap = 8000 if index >= last - 1 else 1200
        if len(content) > cap:
            content = content[-cap:]
        role = "用户" if message.get("role") == "user" else "导演"
        lines.append(role + "：" + content)
    return "\n\n".join(lines)


def scenes_from_talk(director_id, messages=None):
    if director_by_id(director_id) is None:
        raise FileNotFoundError(director_id)
    body = talk_from_messages(messages) if messages else talk_text(30)
    if len(body) < 10:
        raise RuntimeError("对话里还没有能分场的内容。先把这一支片子说清楚，或上传剧本。")
    names = "、".join(
        f"{asset.get('kind')}{asset.get('name')}"
        for asset in ASSETS
        if asset.get("name") and asset.get("kind") != "音频"
    )
    raw = call_model([
        {"role": "system", "content": f"""只根据下面已经聊定的内容分场。对话里没有的人、地点、物件不准加。文件名不是剧情。

以用户最后一次说清的片子为准。更早的导演概述没有放进这段对话。导演答应删掉、不拍、不要的内容，不准写进记住。旧场次和用户最后一次说的冲突时，整场作废，按用户最后一次重新分。

一场只留一件观众必须记住的事。换地方，或要记住的那一件换了，才新开一场。心理、旁白不能单独成场。最多 8 场。

用户说了整支片子的时长，就按这件事怎么发生来分成若干场，每场一个整数秒，4 到 30，加起来接近那个总时长。用户没说时长，也按这一场真正需要的时间写秒数，精确到秒，不要写 0，不要每场都写成同一个数。一场只留一件观众必须记住的事。两件抢，就拆开。

如果对话已经定成一段 25 到 30 秒：导演的一段就是一场，不要把走出来、抬枪、对峙再拆开。导演点了几段就输出几场，按顺序。每场秒数写 25 到 30 之间的一个整数。不要写成 8 秒、9 秒、10 秒、12 秒。

已经有的资产：{names or "还没有"}。地点和画里有谁用这些名字，不要新编一套。

只输出标记：

<<<SCENE>>>
集数：1
地点：
画里有谁：
记住：
秒数：
<<<END>>>

记住这一行只写观众看得见的一件事。"""},
        {"role": "user", "content": body},
    ])
    scenes = split_scenes(raw)
    if not scenes:
        raise RuntimeError("对话里还分不出场。先说清这一支片子发生了什么，或上传剧本。")
    scenes = scenes[:8]
    if segment_locked(messages):
        for scene in scenes:
            try:
                seconds = int(scene.get("seconds") or 0)
            except (TypeError, ValueError):
                seconds = 0
            if seconds < 25 or seconds > 30:
                scene["seconds"] = 28
    return scenes


def style_rows(key):
    if not CURRENT_ID.get("id"):
        return []
    rows = []
    seen = set()
    for item in STYLE.get(key) or []:
        if isinstance(item, str):
            filename, title = item, ""
        elif isinstance(item, dict):
            filename, title = item.get("file") or "", item.get("title") or ""
        else:
            continue
        filename = safe_filename(str(filename))
        if not filename or filename in seen or not (ref_dir() / filename).is_file():
            continue
        seen.add(filename)
        rows.append({"file": filename, "title": str(title or "")[:80]})
    return rows


def style_names():
    return [item["file"] for item in style_rows("files")]


def style_public():
    choices = style_rows("choices")
    uploads = style_rows("uploads")
    names = style_names()
    ready = bool(names)
    return {
        "query": STYLE.get("query") or "",
        "note": STYLE.get("note") or "",
        "file": names[0] if STYLE.get("confirmed") and ready else "",
        "files": names if STYLE.get("confirmed") and ready else [],
        "uploads": uploads,
        "confirmed": bool(STYLE.get("confirmed") and ready),
        "locked_to": STYLE.get("locked_to") or "",
        "phase": STYLE.get("phase") or "",
        "index": STYLE.get("index") or 0,
        "total": STYLE.get("total") or 0,
        "choices": choices,
    }


def sniff_image(raw):
    if raw.startswith(b"\x89PNG"):
        return ".png"
    if raw.startswith(b"\xff\xd8"):
        return ".jpg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return ".webp"
    return ""


def download_image(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urlopen(request, timeout=20) as response:
        kind = (response.headers.get("Content-Type") or "").lower()
        if kind and "image" not in kind and "octet-stream" not in kind:
            return b""
        raw = response.read(8_000_001)
    if len(raw) < 20000 or len(raw) > 8_000_000 or not sniff_image(raw):
        return b""
    return raw


def anchor_query(query, talk):
    return str(query or "").strip()[:120]


def weak_result(title, url):
    hay = (title + " " + url).lower()
    words = ("百科", "baike", "什么意思", "单词", "词典", "翻译", "课件", "xxenglish", "dictionary", "lesson", "biography", "biografia", "steckbrief", "daniels", "wiki")
    return any(word in hay for word in words)


def off_topic(title, url, talk):
    hay = (title + " " + url).lower()
    talk_l = talk.lower()
    banned = ("sphinx", "pyramid", "giza", "egypt", "desert", "金字塔", "狮身人面", "埃及")
    return any(word in hay and word not in talk_l for word in banned)


def bing_hits(query, offset):
    page = Request(
        "https://cn.bing.com/images/async?" + urlencode({
            "q": query,
            "first": str(offset),
            "count": "20",
            "adlt": "off",
        }),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(page, timeout=20) as response:
        html = response.read().decode("utf-8", "replace")
    hits = []
    blobs = re.findall(r'm="\{(.*?)\}"', html) or re.findall(r"m=&quot;\{(.*?)\}&quot;", html)
    for blob in blobs:
        raw = "{" + blob + "}"
        raw = raw.replace("&quot;", '"').replace("&amp;", "&").replace("\\u0026", "&")
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        link = item.get("murl") or ""
        link = link.replace("\\u002f", "/").replace("\\/", "/")
        title = item.get("t") or ""
        if link.startswith("https://"):
            hits.append((link, title))
    if hits:
        return hits
    for link in re.findall(r"murl&quot;:&quot;(.*?)&quot;", html):
        link = link.replace("\\u002f", "/").replace("\\/", "/")
        try:
            link = link.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass
        if link.startswith("https://"):
            hits.append((link, ""))
    return hits


def search_style_batch(queries, talk, offset):
    found = []
    seen = set()
    per_query = 6 if len(queries) == 1 else 2
    for index, query in enumerate(queries):
        try:
            hits = bing_hits(query, offset + index * 10)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        kept = 0
        for link, title in hits:
            if link in seen or off_topic(title, link, talk) or weak_result(title, link):
                continue
            seen.add(link)
            try:
                raw = download_image(link)
            except (HTTPError, URLError, TimeoutError, OSError):
                continue
            if not raw:
                continue
            found.append({"raw": raw, "title": (title or "")[:80]})
            kept += 1
            if kept >= per_query or len(found) >= 6:
                break
        if len(found) >= 6:
            break
    return found[:6]


SHEET_MODELS = {"banana": "nb21", "seedream": "seedream", "image25": "gpt"}


def use_sheet_model(name=None):
    if name in SHEET_MODELS:
        MODE["image"] = name
    if MODE.get("image") not in SHEET_MODELS:
        MODE["image"] = "banana"
    return SHEET_MODELS[MODE["image"]]


def material_prompt(line):
    return (
        "微距材质特写，21:9，表面占满画幅。"
        "不要人物，不要脸，不要手，不要建筑，不要古城，不要水果，不要示意图，不要文字，不要水印。"
        "只保留材质、光和颜色。"
        + line
    )


def style_line(text, name):
    match = re.search(rf"^{name}[:：]\s*(.+)$", text, re.M)
    return match.group(1).strip() if match else ""


def find_style(director_id):
    item = director_by_id(director_id)
    if item is None:
        raise FileNotFoundError(director_id)
    body = talk_text()
    if len(body) < 10:
        raise RuntimeError("先把片子聊清楚，导演才知道要搜什么风格。")
    if STYLE_BUSY.get("on"):
        raise RuntimeError("导演还在找上一张。")
    if TASK["state"] in {"running", "paused", "stopping"}:
        raise RuntimeError("已经有任务在进行。先暂停或终止。")
    task_begin("style", "")
    STYLE_BUSY["on"] = True
    try:
        raw = call_model([
            {"role": "system", "content": f"""你是{item[1]}导演。出资产图之前，必须先搜索风格图。风格图只锁质感：材质、光和颜色。不锁地点，不锁古城，不锁人物。

根据导演刚刚说的质感，一次给四条不同的中文搜索词。每条 6 到 12 个字，只搜一种看得见的表面。只搜索用户当前确认的材质、光和色彩，不返回已放弃的风格。缺少方向时先提出建议，不强行套用某个项目的质感。
不要写古城、废墟、海面全景、人物。不要写英文。不要写角色名，不要写某一部现成片子的名字。

只输出：

<<<STYLE>>>
搜索1：
搜索2：
搜索3：
搜索4：
理由：
<<<END>>>

理由只用一句中文，说这批图要锁的材质和光。不要写地点。"""},
            {"role": "user", "content": body},
        ])
        queries = []
        for index in range(1, 5):
            line = style_line(raw, f"搜索{index}") or style_line(raw, f"搜索 {index}")
            if line:
                queries.append(line.strip("「」\"' "))
        if not queries:
            one = style_line(raw, "搜索")
            queries = [part.strip("「」\"' ") for part in one.split(",") if part.strip()][:4]
        queries = [anchor_query(query, body) for query in queries if query]
        unique = []
        for query in queries:
            if query and query not in unique:
                unique.append(query)
        queries = unique
        if not queries:
            raise RuntimeError("导演没有给出质感。")
        note = style_line(raw, "理由")[:120]
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))
        import banana_client as banana
        queries = queries[:4]
        for old in ref_dir().glob("style*"):
            old.unlink()
        choices = []
        STYLE.update({
            "query": " | ".join(queries)[:240],
            "note": note,
            "file": "",
            "confirmed": False,
            "choices": [],
            "phase": "plate",
            "index": 0,
            "total": len(queries),
        })
        save_session()
        for index, query in enumerate(queries, start=1):
            STYLE["index"] = index
            save_session()
            dest = ref_dir() / f"style_{index}.png"
            task_label(f"第 {index}/{len(queries)} 张")
            try:
                generate_sheet(
                    banana,
                    material_prompt(query),
                    dest,
                    aspect="21:9",
                    resolution="1K",
                    seed=41000 + index,
                    model=use_sheet_model(),
                )
            except banana.BananaError as exc:
                if choices:
                    continue
                detail = str(exc)[:300]
                raise RuntimeError(f"风格图停在第 {index} 张。{detail}") from exc
            if dest.is_file():
                choices.append({"file": dest.name, "title": query[:40]})
        if not choices:
            raise RuntimeError("风格图没有出成。")
        STYLE.update({"choices": choices, "phase": "", "index": 0, "total": 0})
        save_session()
        return style_public()
    except TaskStopped:
        raise RuntimeError("已终止")
    finally:
        STYLE_BUSY["on"] = False
        task_finish("style")
        if STYLE.get("phase") in {"plate", "paused"}:
            STYLE["phase"] = ""
            save_session()


def confirm_style(filename="", files=None):
    wanted = []
    if isinstance(files, list):
        for item in files:
            name = safe_filename(str(item or ""))
            if name:
                wanted.append(name)
    if not wanted and filename:
        wanted = [safe_filename(str(filename))]
    names = []
    for name in wanted:
        if name and name not in names and (ref_dir() / name).is_file():
            names.append(name)
    if not names:
        raise RuntimeError("先把 Midjourney 的图传上来。")
    if len(names) > 8:
        raise RuntimeError("风格参考一次最多 8 张。")
    if names != style_names():
        active().intelligence["style_version"] += 1
        for asset in ASSETS:
            if asset.get("kind") != "音频":
                asset["needs_redraw"] = True
    STYLE["files"] = names
    STYLE["file"] = names[0]
    STYLE["confirmed"] = True
    STYLE["locked_to"] = latest_director_text()[:240]
    save_session()
    return style_public()


def add_style_upload(name, raw):
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("单张风格图不要超过 15MB")
    suffix = Path(safe_filename(name)).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    folder = ref_dir()
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while (folder / f"mj_{number}{suffix}").exists():
        number += 1
        if number > 40:
            raise ValueError("风格图太多了。先确认手上这批。")
    dest = folder / f"mj_{number}{suffix}"
    dest.write_bytes(raw)
    uploads = style_rows("uploads")
    uploads.append({"file": dest.name, "title": Path(safe_filename(name)).stem[:40]})
    if len(uploads) > 8:
        dest.unlink(missing_ok=True)
        raise ValueError("风格参考一次最多 8 张。")
    STYLE["uploads"] = uploads
    STYLE["confirmed"] = False
    STYLE["file"] = ""
    save_session()
    return style_public()


def look_rejected():
    return any(a.get("needs_redraw") for a in ASSETS)


def director_retired(name):
    text = latest_director_text()
    name = (name or "").strip()
    if not text or not name:
        return False
    for line in text.splitlines():
        head = line.strip().replace("*", "")
        head = re.sub(r"^[-•\d.、]+\s*", "", head)
        if "：" not in head:
            continue
        title = head.split("：", 1)[0].strip()
        if title == name and any(word in head for word in ("不用", "停用")):
            return True
    return False


def kept_names():
    text = latest_director_text()
    if "只保留" not in text and "删除" not in text:
        return []
    names = []
    for line in text.splitlines():
        raw = line.strip().replace("*", "")
        if not re.match(r"^\d+[.、]", raw):
            continue
        head = re.sub(r"^[\d.、]+\s*", "", raw).strip()
        head = re.split(r"[\s—\-：:]", head, maxsplit=1)[0].strip()
        if head and len(head) <= 24:
            names.append(head)
    return names


def redraw_names():
    text = latest_director_text()
    names = []
    armed = False
    for line in text.splitlines():
        raw = line.strip().replace("*", "")
        if any(word in raw for word in ("只需重出", "只需画出", "只重出", "只画出")):
            armed = True
            continue
        if not armed:
            continue
        if re.match(r"^[-•]", raw) or re.match(r"^\d+[.、]", raw):
            head = re.sub(r"^[-•\d.、]+\s*", "", raw).strip()
            head = re.split(r"[\s—\-：:]", head, maxsplit=1)[0].strip()
            if head and len(head) <= 24 and "其他" not in head and "其余" not in head:
                names.append(head)
            continue
        if raw:
            armed = False
    return names


def kept_baseline():
    text = latest_director_text().replace("*", "")
    match = re.search(r"保留的只有[:：]\s*([^。]+)", text)
    if not match:
        return []
    names = []
    for part in re.split(r"[、，,]", match.group(1)):
        part = part.strip()
        if part and part not in names:
            names.append(part)
    return names


def title_parts(title):
    return [part for part in re.split(r"[、，,：:\s]+", title) if part] or [title]


def resolve_title(title):
    names = [a.get("name") or "" for a in ASSETS]
    if title in names:
        return title
    found = [name for name in names if title and (title in name or name in title)]
    return found[0] if len(found) == 1 else ""


def above_titles():
    text = latest_director_text()
    return [a["name"] for a in ASSETS if a.get("name") and a["name"] in text]


def redraw_titles():
    text = latest_director_text()
    if not any(word in text for word in ("重出", "重画")):
        return []
    return above_titles()


def explicit_draw_names():
    changed = [a["name"] for a in ASSETS if a.get("needs_redraw") and a.get("name")]
    if changed:
        return changed
    text = latest_director_text().replace("*", "")
    protected = set(kept_baseline())
    names = []
    for title in redraw_titles():
        name = resolve_title(title)
        if name and name not in protected and name not in names and "人形" not in name:
            names.append(name)
    if names and ("全部重出" in text or "重出以上" in text):
        return names
    for name in redraw_names():
        if name not in protected and name not in names and "人形" not in name:
            names.append(name)
    for match in re.finditer(r"(?:要锁住|重画|重出|画出)[:：]\s*([^。]+)", text):
        for part in re.split(r"[、，,]", match.group(1)):
            part = re.sub(r"^(以及|和|与)\s*", "", part.strip())
            part = re.split(r"[；;]", part)[0].strip()
            if part and 1 < len(part) <= 24 and part not in names and part not in protected and "人形" not in part:
                names.append(part)
    for match in re.finditer(r"把现有的([^。]+?)重画", text):
        for part in re.split(r"[、，,和与]", match.group(1)):
            part = part.strip()
            if part and 1 < len(part) <= 24 and part not in names and part not in protected and "人形" not in part:
                names.append(part)
    return names


def apply_redraw_lines(names):
    # Approved structured plans carry asset edits; prose does not overwrite them.
    return


def ensure_named_assets(names):
    if "不新增" in latest_director_text():
        return
    for name in names:
        if any((asset.get("name") or "") == name for asset in ASSETS):
            continue
        kind = "人物"
        if any(word in name for word in ("石窟", "战场", "城")):
            kind = "场景"
        elif any(word in name for word in ("枪", "轮", "绫", "圈")):
            kind = "道具"
        ASSETS.append({"kind": kind, "name": name, "picture": name, "file": "", "drawn": ""})


def dropped_names():
    text = latest_director_text()
    names = []
    armed = False
    for line in text.splitlines():
        raw = line.strip().replace("*", "")
        if any(word in raw for word in ("删除", "不用", "停用")) and not re.match(r"^[-•]", raw):
            armed = True
            continue
        if not armed:
            continue
        if re.match(r"^[-•]", raw):
            head = re.sub(r"^[-•]\s*", "", raw).strip()
            head = re.split(r"[\s—\-：:，,]", head, maxsplit=1)[0].strip()
            if head and len(head) <= 24 and "其他" not in head:
                names.append(head)
            continue
        if raw:
            armed = False
    return names


def asset_wanted(asset, found_names=None):
    name = (asset.get("name") or "").strip()
    if not name or asset.get("kind") == "音频" or "风格图" in name or director_retired(name) or name in dropped_names() or name in kept_baseline():
        return False
    focus = list(found_names) if found_names else (explicit_draw_names() or fresh_sheet_names())
    if name not in focus:
        return False
    if name in explicit_draw_names():
        return True
    if asset.get("file") and not asset_stale(asset):
        return False
    return True


def replacement_target(asset):
    if asset.get("file"):
        return None
    name = (asset.get("name") or "").strip()
    kind = asset.get("kind") or ""
    if not name or not kind:
        return None
    filled = [
        item for item in ASSETS
        if item is not asset and item.get("kind") == kind and item.get("file") and not director_retired(item.get("name") or "")
    ]
    by_name = [
        item for item in filled
        if item.get("name") and item.get("name") != name and (name in item.get("name") or item.get("name") in name)
    ]
    if len(by_name) == 1:
        target = by_name[0]
        target_name = target.get("name") or ""
        if target_name in dropped_names() or director_retired(target_name):
            return target
    return None


def fold_replacements():
    if explicit_draw_names() or not look_rejected():
        return
    for asset in list(ASSETS):
        if "风格图" in (asset.get("name") or ""):
            continue
        if not asset_wanted(asset):
            continue
        target = replacement_target(asset)
        if target is None or target not in ASSETS:
            continue
        brief = (asset.get("picture") or "").strip()
        if not brief or is_review_picture(brief):
            continue
        target["picture"] = brief
        target["version"] = int(target.get("version") or 1) + 1
        target["needs_redraw"] = True
        target.pop("confirmation", None)
        target["name"] = asset.get("name") or target.get("name")
        ASSETS.remove(asset)


def look_key():
    return str(active().intelligence["style_version"]) + ":" + "|".join(style_names())


def asset_stale(asset):
    if asset.get("kind") == "音频":
        return False
    if not asset.get("file") or asset.get("needs_redraw"):
        return True
    # Legacy assets have no explicit version: keep them usable until changed.
    if asset.get("style_version", active().intelligence["style_version"]) != active().intelligence["style_version"]:
        return True
    return bool(asset.get("drawn")) and asset["drawn"] != (asset.get("picture") or "").strip()


def assets_need_redraw():
    used = {aid for scene in SCENES for aid in scene.get("asset_ids") or []}
    return any(asset_stale(a) for a in ASSETS if a.get("kind") != "音频" and (a.get("needs_redraw") or a.get("id") in used))


def names_match(left, right):
    a = (left or "").strip()
    b = (right or "").strip()
    return bool(a and b and (a == b or a in b or b in a))


def same_name(left, right):
    a = (left or "").strip()
    b = (right or "").strip()
    return bool(a and b and a == b)


def is_review_picture(picture):
    marks = ("需要重出", "重出", "不够用", "写实", "不能用", "不要用", "完全不用", "停用", "不是资产", "先别")
    return any(mark in (picture or "") for mark in marks)


def listed_assets(text):
    if any(mark in (text or "") for mark in ("换风格", "重新定一张", "不要直接混用")):
        return []
    if not re.search(r"资产图|补.{0,8}张|新增", text or ""):
        return []
    rows = []
    for raw in text.splitlines():
        line = raw.strip().replace("**", "")
        if not re.match(r"^(?:[-*•]|\d+[.、])", line):
            continue
        line = re.sub(r"^(?:[-*•]|\d+[.、])\s*", "", line).strip()
        if "：" not in line:
            continue
        name, picture = line.split("：", 1)
        name = name.strip()
        picture = picture.strip()
        if not name or not picture or len(name) > 16:
            continue
        if is_review_picture(picture):
            continue
        if any(mark in name for mark in "，。！？；"):
            continue
        kind = "人物"
        blob = name + picture
        if any(word in name for word in ("枪", "圈", "绫", "轮", "斧", "葫芦", "牌")):
            kind = "道具"
        elif "兽" not in blob and any(word in name for word in ("城", "景")):
            kind = "场景"
        rows.append({"kind": kind, "name": name, "picture": picture, "file": ""})
    return rows


def latest_director_text():
    for message in reversed(CHAT.get("messages") or []):
        if message.get("role") == "assistant":
            return (message.get("content") or "").strip()
    return ""


def latest_prompt_text():
    for message in reversed(CHAT.get("messages") or []):
        if message.get("role") != "assistant":
            continue
        content = (message.get("content") or "").strip()
        if content and not is_status_bubble(content):
            return content
    return ""


def latest_exchange():
    rows = usable_messages(CHAT.get("messages") or [])
    if not rows:
        return []
    last = len(rows) - 1
    start = last
    if rows[last].get("role") == "assistant":
        for index in range(last - 1, -1, -1):
            if rows[index].get("role") == "user":
                start = index
                break
    return rows[start:]


def recent_asset_talk():
    rows = usable_messages(CHAT.get("messages") or [])
    if not rows:
        return []
    assistant_at = [index for index, message in enumerate(rows) if message.get("role") == "assistant"]
    if not assistant_at:
        return rows[-4:]
    start = assistant_at[-2] if len(assistant_at) >= 2 else assistant_at[-1]
    return rows[start:]


def current_sheet_names():
    names = []
    for asset in ASSETS:
        name = (asset.get("name") or "").strip()
        if not name or asset.get("kind") == "音频" or "风格图" in name or "人形" in name:
            continue
        if name not in names:
            names.append(name)
    return names


def drop_asset_file(asset):
    filename = safe_filename(asset.get("file") or "")
    if not filename:
        return
    root = lib().resolve()
    target = (root / filename).resolve()
    if target.parent == root and target.is_file():
        target.unlink()


def apply_asset_marks(text, keep_files=False, only=None):
    rows = split_assets(text)
    if not rows:
        return text
    allowed = {name for name in (only or []) if name}
    for row in rows:
        if allowed and row.get("name") not in allowed:
            continue
        target = next((
            asset for asset in ASSETS
            if asset.get("kind") == row["kind"] and same_name(asset.get("name"), row["name"])
        ), None)
        brief = row["picture"].strip()
        if target is None:
            ASSETS.append(row)
            continue
        if (target.get("picture") or "").strip() == brief and target.get("file"):
            continue
        if not keep_files:
            drop_asset_file(target)
            target["file"] = ""
            target["drawn"] = ""
        target["picture"] = brief
    save_session()
    cleaned = re.sub(r"<<<ASSET>>>.*?<<<END>>>", "", text, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _add_sheet_name(found, part):
    part = (part or "").replace("*", "").replace("`", "")
    part = part.strip(" 《》「」“”\"'")
    part = re.split(r"[；;。！？\n]", part)[0].strip()
    part = re.sub(r"^(以及|和|与)\s*", "", part).strip()
    if not part or part in found or not (2 <= len(part) <= 40):
        return
    if any(mark in part for mark in ("不要", "不照搬", "只用来", "参考图", "其他", "其余", "只调用", "重画", "重出", "：", ":")):
        return
    found.append(part)


def latest_round_names():
    text = latest_prompt_text().replace("*", "")
    if not text:
        return []
    found = []
    for match in re.finditer(r"(?:只调用|重画|重出|画出|要锁住)[:：]\s*([^。\n]+)", text):
        for part in re.split(r"[、，,]", match.group(1)):
            _add_sheet_name(found, part)
    for row in split_assets(text):
        _add_sheet_name(found, row.get("name") or "")
    known = {(asset.get("name") or "").strip() for asset in ASSETS}
    known.discard("")
    for match in re.finditer(r"([^\s。；;\n]{2,40}(?:、[^\s。；;\n]{2,40}){1,12})", text):
        parts = [item.strip() for item in match.group(1).split("、")]
        hits = [item for item in parts if "_" in item or item in known]
        if len(hits) >= 2:
            for item in hits:
                _add_sheet_name(found, item)
    for line in text.splitlines():
        raw = line.strip().replace("*", "")
        if not re.match(r"^(?:[-*•]|\d+[.、])", raw):
            continue
        raw = re.sub(r"^(?:[-*•]|\d+[.、])\s*", "", raw).strip()
        head = re.split(r"[：:，,。\s—\-]", raw, maxsplit=1)[0].strip()
        if head and ("_" in head or head in known) and len(head) <= 40:
            _add_sheet_name(found, head)
    if not found:
        return []
    if "关系图" in text:
        stems = []
        for item in found:
            stem = item.split("_")[0]
            if stem and stem not in stems:
                stems.append(stem)
        for asset in ASSETS:
            name = (asset.get("name") or "").strip()
            if not name or name in found:
                continue
            if "体型" not in name and "关系" not in name:
                continue
            if any(stem and stem in name for stem in stems):
                found.append(name)
                break
    return found


def fresh_sheet_names():
    named = latest_round_names()
    if not named:
        return []
    blocked = set(dropped_names()) | set(kept_baseline())
    names = []
    for name in named:
        if name in blocked or name in names:
            continue
        asset = next((item for item in ASSETS if (item.get("name") or "") == name), None)
        if asset is None:
            names.append(name)
            continue
        if asset.get("kind") == "音频" or "风格图" in name or "人形" in name:
            continue
        if (asset.get("file") or "").strip() and not asset_stale(asset):
            continue
        names.append(name)
    return names


def style_replaced():
    return any(a.get("style_version", 1) != active().intelligence["style_version"] for a in ASSETS if a.get("file"))


def make_all_assets(director_id, ratio, image_model="banana", fingerprint=None):
    return WORKFLOW.draw(director_id, ratio, image_model, fingerprint)

def still_field(block, name):
    match = re.search(rf"^{name}[:：]\s*(.*)$", block, re.M)
    return match.group(1).strip() if match else ""


def split_stills(text):
    rows = []
    for match in re.finditer(r"<<<STILL>>>(.*?)<<<END>>>", text, re.S):
        block = match.group(1)
        name = still_field(block, "名称")
        use = still_field(block, "用途")
        picture = still_field(block, "画面")
        if picture:
            rows.append({"name": name or "静帧", "use": use, "picture": picture})
    return rows[:4]


def still_prompt(director_id, place, who, remember, ratio):
    item = director_by_id(director_id)
    if item is None or not item[3].exists():
        raise FileNotFoundError(director_id)
    skill = ""  # Shared Skill is injected by INTELLIGENCE.prepare.
    return f"""你是{item[1]}导演。这次只给当前出图模型写静帧，不写视频提示词，不写秒数，不写运镜。

一场最多四张。一张只锁一件：一个人、一个地点，或一件道具。不要把几个角度拼在一张图里。不要写价格、Logo、包装文字。

画面写这一张静止的图：什么在画里、朝向、光从哪边来、要认出的那一面。

这张参考图画幅是 21:9。它只锁外形，成片尺寸另算，不要把 21:9 写成视频画幅。

技能只用来判断该锁什么，不要输出视频时间轴。

{skill}

只输出静帧，标记必须原样出现：

<<<STILL>>>
名称：
用途：
画面：
<<<END>>>

这一场
地点：{place}
画里有谁：{who}
记住：{remember}
"""


def make_stills(director_id, place, who, remember, ratio, scene_no):
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    import banana_client as banana
    if ratio not in {"16:9", "9:16", "1:1"}:
        ratio = "16:9"
    task_begin("draw", "静帧")
    try:
        return _make_stills(banana, director_id, place, who, remember, ratio, scene_no)
    except TaskStopped:
        raise RuntimeError("已终止")
    finally:
        task_finish("draw")


def _make_stills(banana, director_id, place, who, remember, ratio, scene_no):
    raw = call_model([
        {"role": "system", "content": still_prompt(director_id, place, who, remember, ratio)},
        {"role": "user", "content": "只写这一场要用的静帧。"},
    ])
    briefs = split_stills(raw)
    if not briefs:
        raise RuntimeError("这一场没有写出静帧。")
    if len(list_assets()) + len(briefs) > 50:
        raise RuntimeError("图库最多 50 张。先删掉不用的再出。")
    lib().mkdir(exist_ok=True)
    saved = []
    for index, brief in enumerate(briefs, start=1):
        filename = safe_filename(f"场{scene_no}_{index}_{brief['name']}.png")
        dest = lib() / filename
        task_label(f"第 {index}/{len(briefs)} 张 · {brief['name']}")
        try:
            generate_sheet(
                banana,
                brief["picture"],
                dest,
                aspect=ASSET_ASPECT,
                resolution="1K",
                seed=21000 + int(scene_no) * 10 + index,
                model=use_sheet_model(),
            )
        except banana.BananaError as exc:
            detail = str(exc)
            if len(detail) > 400:
                detail = detail[:400]
            raise RuntimeError(f"出图停在第 {index} 张。{detail}") from exc
        saved.append({"name": dest.name, "use": brief["use"], "picture": brief["picture"]})
    return saved


def assets_for_scene(scene):
    return INTELLIGENCE.payload(scene)["assets"]


def audios_for_scene(scene):
    return INTELLIGENCE.payload(scene)["audios"]


def asset_lines():
    lines = []
    image_no = 1
    audio_no = 1
    duties = {
        "人物": "只锁身份和衣服，不取白底、四格和站姿。",
        "场景": "只锁这个地点，不取人。",
        "道具": "只锁这一件的外形和要认出的那一面，不取白底。",
    }
    for asset in ASSETS:
        if not asset.get("file"):
            continue
        if asset.get("kind") == "音频":
            if MODE.get("video") == "h3": continue
            lines.append(f"@音频{audio_no} 文件 {asset['file']} 是音频「{asset['name']}」。只锁这段声音，不取画面。")
            audio_no += 1
        else:
            duty = duties.get(asset.get("kind") or "", "只锁这一件。")
            token = f"<Picture {image_no}>" if MODE.get("video") == "h3" else f"@图片{image_no}"
            lines.append(f"{token} 文件 {asset['file']} 是{asset['kind']}「{asset['name']}」。{duty}")
            image_no += 1
    return "\n".join(lines)


def write_asset_prompts(director_id, messages, only=None, trimmed=False):
    item = director_by_id(director_id)
    if item is None:
        raise FileNotFoundError(director_id)
    if not messages:
        bound = latest_exchange()
    elif trimmed:
        bound = usable_messages(messages)
    else:
        bound = story_messages(messages)
    body = talk_from_messages(bound)
    names = [name for name in (only or []) if name]
    if names and not latest_round_names():
        unfiled = []
        for name in names:
            asset = next((item for item in ASSETS if (item.get("name") or "") == name), None)
            if asset is not None and not (asset.get("file") or "").strip():
                unfiled.append(name)
        scope = (
            "只能用这些现有名字："
            + "、".join(names)
            + "。"
            + (("还没画的是：" + "、".join(unfiled) + "。") if unfiled else "")
            + "必须为指定的每个资产写完整草稿，不新增名字。用户明确重新写词的资产即使已经画好也可以写。"
        )
    else:
        scope = "、".join(names) if names else "你刚刚点名的那几张"
    raw = call_model([
        {"role": "system", "content": f"""你是{item[1]}导演。用户明确请你写资产提示词草稿。根据当前项目记忆、用户已选择的参考视频分析和导演讨论写完整最终生图提示词，不会直接生成。这次只写静帧，不写视频，不写秒数，不写运镜。

只写这几张：{scope}。一张一段。先用平常的话写出这一张的画面，再附上标记。画幅写 21:9。这只是这张参考图，用来锁外形，不要把它写成成片的画幅。分辨率写 1K。已经说保留的不要重写。不要加入用户未要求的主体或物件。不要输出 <<<SEEDANCE>>>。

<<<ASSET>>>
种类：人物
名称：
画面：
<<<END>>>

种类只写人物、道具、场景。画面字段必须是可直接提交的完整生图提示词，包括需要的构图、背景、材质、光线、参考职责及限制。人物或道具需要白底/多视图时在这里明确写，场景按场景需要；不要依赖后续程序添加任何词。质感遵循当前已确认设定，不要恢复放弃的画风。"""},
        {"role": "user", "content": body or "按刚才点名的那几张写。"},
    ])
    task_gate()
    written = [row.get("name") or "" for row in split_assets(raw) if row.get("name")]
    if names:
        written = [name for name in written if name in names]
    talk = apply_asset_marks(raw, keep_files=True, only=names or written)
    if not talk:
        talk = (raw or "").strip()
    return {"talk": talk, "scenes": list(SCENES), "assets": list(ASSETS), "stills": True, "written": written}


def write_prompts(director_id, messages, episode, ratio):
    if WRITING["on"]:
        raise RuntimeError("上一份提示词还在写。等它停下再点。")
    if TASK["state"] in {"running", "paused", "stopping"}:
        raise RuntimeError("已经有任务在进行。先暂停或终止。")
    task_begin("write", "")
    WRITING["on"] = True
    try:
        return _write_prompts(director_id, messages, episode, ratio)
    except TaskStopped:
        raise RuntimeError("已终止")
    finally:
        WRITING["on"] = False
        task_finish("write")


def _write_prompts(director_id, messages, episode, ratio):
    if director_by_id(director_id) is None:
        raise FileNotFoundError(director_id)
    if not any(asset.get("file") for asset in ASSETS if asset.get("kind") != "音频"):
        return write_asset_prompts(director_id, messages)
    bound = story_messages(messages or CHAT.get("messages") or [])
    fresh = [dict(scene) for scene in SCENES] if SCENES else scenes_from_talk(director_id, bound)
    chosen = [scene for scene in fresh if not scene.get("prompt") or scene.get("needs_rewrite")]
    if episode:
        chosen = [scene for scene in fresh if int(scene.get("episode") or 1) == int(episode)]
        if not chosen:
            raise RuntimeError(f"分场里没有第 {episode} 集。")
    if not chosen:
        return {"talk": "当前提示词仍有效，无需重写。", "scenes": SCENES}
    listing = "\n".join(
        f"第{scene.get('episode') or 1}集 场{index} {scene.get('seconds') or '未定'}秒 地点：{scene.get('place')} 画里有谁：{scene.get('who')} 记住：{scene.get('remember')}"
        for index, scene in enumerate(chosen, start=1)
    )
    extra = (
        f"只写下面这些场，一场一个标记，按顺序。这些场刚按用户最后一次说的片子分过。和当前确认要求冲突的旧内容不要写回来。质感按当前项目记忆与确认参考图。设置第一行写「场次：N」，N 用下面的场号。"
        f"用户指定的集数是 {episode or '未指定，按对话和下面的场来'}。不要在成片提示词里写画幅。参考图和资产图是 21:9，只供参考，成片尺寸以提交按钮为准。"
        "人物图只锁身份和衣服，不取参考里的白底、拼图或无关站姿。"
        "道具图只锁这一件，不取白底。场景图不是白底，只锁地点。"
        "音频只锁声音，不取画面。没有列出来的图和声音不要编。"
        "你是这一支片子的导演，不是在填一张检查表。先看整支片子要让观众记住什么，再决定分几场、每一场几秒。秒数按动作本身来，精确到秒。接口一条只能交 4 到 30 秒，这是机器的限度，不是创作模板。不要为了凑满 30 秒把一个动作拉长，也不要把一场收成四行概述。\n"
        + (
            "这场已经按导演的一段定好，一段就是一场，秒数在 25 到 30。不要再拆短，不要改秒数。引用只按当前模型导演规则和实际资产编号，不添加其他模型的模式字段。\n"
            if segment_locked(bound)
            else ""
        )
        + "提示词要能直接开拍。人在哪、朝哪、手里是什么、景别、镜头怎么动、光从哪来，都写到能执行。有变化的那一秒写死。没有新事的秒留在同一段里，不要从 0 秒报到最后一秒。声音和配音也只写在发生变化的那一秒：谁在说、原句、气口、嘴、环境声让到哪、哪一下声音确认这件事。用户给了原句才配这句。用户说了不要台词，就不要编词，把没有人声的那一层做成能听出场所、距离和材质的声音。画面不写字幕。这些规则在写的这一步自己遵守。\n"
        + script_beat_rule()
        + "\n"
        "素材职责写在最前。每张图只干一件，写清不取什么。没有的图不要编。\n"
        + listing
        + "\n\n资产编号：\n"
        + (asset_lines() or "这一集还没有静帧。不要写 @图片。")
        + "\n\n下面附了资产文件夹里已经出好的画面，每张前面有种类和名称。质感按这些画面，不要按旧对话猜。没附上画面的不要写成已经看见。用户上传的参考图会单独标出来，那不是资产图。"
    )
    packed = [{"role": "system", "content": system_prompt(director_id)}]
    for message in bound[-12:]:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            packed.append({"role": role, "content": content})
    packed.append({"role": "user", "content": extra})
    raw = call_model(with_ref_images(packed))
    task_gate()
    talk, takes = split_reply(raw)
    used = set()
    for index, scene in enumerate(chosen, start=1):
        match = None
        for take_index, take in enumerate(takes):
            if take_index in used:
                continue
            number = re.search(r"场次\s*[:：]\s*(\d+)", take.get("settings") or "")
            if number and int(number.group(1)) == index:
                match = take
                used.add(take_index)
                break
        if match is None and len(takes) == len(chosen) and index - 1 < len(takes) and (index - 1) not in used:
            match = takes[index - 1]
            used.add(index - 1)
        scene["prompt"] = ""
        scene["settings"] = ""
        scene["warnings"] = []
        if not match:
            continue
        scene["prompt"] = match["prompt"]
        scene["needs_rewrite"] = False
        scene["settings"] = match["settings"]
        scene["warnings"] = match["warnings"]
    if not all(scene.get("prompt") for scene in chosen):
        raise RuntimeError("提示词没有写全。场次保持原样，可以再点一次。")
    SCENES.clear()
    SCENES.extend(fresh)
    INTELLIGENCE.identify()
    for scene in SCENES:
        if scene in chosen:
            scene.pop("reference_bindings", None)
        INTELLIGENCE.payload(scene)
    PROMPT_FROM["text"] = story_anchor(bound)
    save_session()
    return {"talk": talk, "scenes": SCENES}


def history_node(prompt_id):
    try:
        with urlopen(comfy_base() + "/history/" + prompt_id, timeout=10) as response:
            hist = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    node = hist.get(prompt_id) if isinstance(hist, dict) else None
    if not isinstance(node, dict):
        return None
    return node


def history_error(prompt_id):
    node = history_node(prompt_id)
    if not node:
        return ""
    status = node.get("status") if isinstance(node.get("status"), dict) else {}
    for msg in status.get("messages") or []:
        if isinstance(msg, (list, tuple)) and msg and msg[0] == "execution_error":
            detail = msg[1] if len(msg) > 1 and isinstance(msg[1], dict) else {}
            text = str(detail.get("exception_message") or "").strip()
            return text[:400] or "这一场生成失败"
    if status.get("status_str") == "error":
        return "这一场生成失败"
    return ""


def history_video(prompt_id):
    node = history_node(prompt_id)
    if not node:
        return ""
    blob = json.dumps(node, ensure_ascii=False).replace("\\\\", "\\")
    paths = re.findall(r"[A-Za-z]:\\[^\"\r\n]+?\.mp4", blob)
    for item in paths:
        path = Path(item)
        if path.is_file():
            return str(path)
    root = Path(load_config().get("comfy_output_dir") or r"D:\ComfyUI\output")
    for output in (node.get("outputs") or {}).values():
        if not isinstance(output, dict):
            continue
        for key in ("videos", "gifs", "images"):
            for item in output.get(key) or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("filename") or ""
                if not str(name).lower().endswith(".mp4"):
                    continue
                sub = item.get("subfolder") or ""
                path = root / sub / name if sub else root / name
                if path.is_file():
                    return str(path)
    return ""


def concat_films(files):
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    folder = Path(START_CONFIG.get("output_dir") or desktop)
    stem = safe_filename(Path(SCRIPT.get("name") or "急急").stem)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = folder / f"{stem}_成片_{stamp}_{uuid.uuid4().hex[:4]}.mp4"
    try:
        return media.concatenate(files, dest, project_dir() / "assembly")
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("片段已保存，合片没有完成：" + str(exc)[:300]) from exc


def film_file():
    raw = JOB.get("film") or ""
    if not raw:
        return None
    path = Path(raw).resolve()
    if path.suffix.lower() != ".mp4" or not path.is_file():
        return None
    roots = [
        Path(START_CONFIG.get("output_dir") or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop").resolve(),
        OUTPUT_DIR.resolve(),
        Path(load_config().get("comfy_output_dir") or r"D:\ComfyUI\output").resolve(),
    ]
    if not any(path == root or root in path.parents for root in roots):
        return None
    return path


def watch_episode():
    if TASK["state"] == "idle" and JOB.get("phase") == "running":
        task_begin("video", "")
    deadline = time.time() + 3600
    try:
        while time.time() < deadline:
            try:
                task_gate()
            except TaskStopped:
                JOB["phase"] = "error"
                JOB["error"] = "已终止"
                save_session()
                return
            pending = False
            for job in JOB["jobs"]:
                if job.get("file") or job.get("status") == "error":
                    continue
                pending = True
                if job.get("status") == "held" or TASK.get("state") in {"paused", "stopping"}:
                    continue
                err = history_error(job.get("prompt_id") or "")
                if err:
                    if TASK_STOP.is_set() or TASK.get("state") in {"paused", "stopping"}:
                        job["status"] = "held"
                        continue
                    job["status"] = "error"
                    job["error"] = err
                    save_session()
                    continue
                found = history_video(job.get("prompt_id") or "")
                if found:
                    job["file"] = found
                    job["status"] = "done"
                    save_session()
            failed = [job.get("error") for job in JOB["jobs"] if job.get("status") == "error"]
            if failed and TASK.get("state") not in {"paused", "stopping"} and not TASK_STOP.is_set():
                JOB["phase"] = "error"
                JOB["error"] = failed[0] or "这一场生成失败"
                save_session()
                return
            if not pending:
                break
            time.sleep(8)
        files = [job.get("file") for job in JOB["jobs"]]
        if not files or not all(files):
            JOB["phase"] = "error"
            JOB["error"] = "还有场没有出完，成片先不接。"
            save_session()
            return
        try:
            JOB["film"] = concat_films(files)
            JOB["phase"] = "done"
            JOB["error"] = ""
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            JOB["phase"] = "error"
            JOB["error"] = str(exc)[:400]
        save_session()
    finally:
        task_finish("video")
    if JOB.get("phase") == "done" and active().intelligence.get("auto_review"):
        task_begin("review", "抽样检查成片")
        try:
            INTELLIGENCE.review("video")
        except Exception as exc:
            active().intelligence["reviews"].append({"id": uuid.uuid4().hex, "at": time.time(), "kind": "video", "text": "自动检查未完成：" + str(exc), "limitations": "成片已保存，检查失败不触发重生成。"})
            save_session()
        finally:
            task_finish("review")


def latest_turn():
    for message in reversed(CHAT.get("messages") or []):
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = (message.get("content") or "").strip()
        if not content or (role == "assistant" and is_status_bubble(content)):
            continue
        return role, content
    return "", ""


def rewrite_requested(text):
    raw = (text or "").strip()
    if not raw or raw.count("缺") >= 3:
        return False
    asks = ("写提示词", "重写提示词", "按对话写", "按对话重写", "写视频提示词", "把提示词写出来", "重新写提示词")
    return any(phrase in raw for phrase in asks)


def prompt_is_patch(text):
    raw = text or ""
    return any(phrase in raw for phrase in ("只补", "不改原来", "不改原有", "覆盖对应"))


def time_ranges(text):
    return list(re.finditer(r"(\d+)\s*[-–—~到至]\s*(\d+)\s*(?:秒|s)", text or "", re.I))


def director_scene_parts(text):
    matches = list(re.finditer(r"第\s*\d+\s*场", text or ""))
    if not matches:
        return []
    parts = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        part = text[match.start():end].strip()
        if part:
            parts.append(part)
    return parts


def film_prompt_blocks(text):
    raw = text or ""
    _, takes = split_reply(raw)
    marked = [take.get("prompt") or "" for take in takes if (take.get("prompt") or "").strip()]
    if marked:
        return marked
    parts = director_scene_parts(raw)
    if parts:
        return parts
    if time_ranges(raw):
        return [raw.strip()]
    return []


def looks_like_full_prompt(text):
    raw = text or ""
    if not raw or prompt_is_patch(raw):
        return False
    if "<<<SEEDANCE>>>" in raw or "<<<VIDEO>>>" in raw:
        return True
    ranges = time_ranges(raw)
    if len(ranges) < 2:
        return False
    return raw.count("环境") >= len(ranges) and raw.count("景别") >= len(ranges)


def blocks_are_complete(blocks):
    if not blocks:
        return False
    for block in blocks:
        ranges = time_ranges(block)
        if not ranges:
            return False
        if lint_scene_prompt(block, int(ranges[-1].group(2))):
            return False
    return True


def film_blocks_error(blocks):
    scenes = []
    for index, block in enumerate(blocks, start=1):
        ranges = time_ranges(block)
        seconds = int(ranges[-1].group(2)) if ranges else 0
        scenes.append({"prompt": block, "seconds": seconds, "place": f"第{index}场"})
    return prompt_lint_error(scenes)


def adopt_director_prompts(blocks):
    if not blocks or len(blocks) != len(SCENES):
        raise RuntimeError("提示词场数和分镜数不一致，不能按位置猜测绑定。")
    for scene, block in zip(SCENES, blocks):
        scene["prompt"] = block.strip()
        ranges = time_ranges(block)
        if ranges:
            scene["seconds"] = int(ranges[-1].group(2))
        scene["needs_rewrite"] = False
    PROMPT_FROM["text"] = story_anchor(CHAT.get("messages") or [])
    save_session()


def keep_written_prompts():
    if not any((scene.get("prompt") or "").strip() for scene in SCENES):
        raise RuntimeError("最新一条还不是能交的成片词，没有写、没有提交。")
    PROMPT_FROM["text"] = story_anchor(CHAT.get("messages") or [])
    save_session()


def scene_prompts_ready():
    ready = [scene for scene in SCENES if (scene.get("prompt") or "").strip()]
    if not ready:
        return False
    anchor = story_anchor(CHAT.get("messages") or [])
    if anchor != (PROMPT_FROM.get("text") or ""):
        return False
    if segment_locked() and any(not (25 <= int(scene.get("seconds") or 0) <= 30) for scene in ready):
        return False
    return True


def fill_scene_prompts(director_id, ratio):
    if not director_id:
        raise RuntimeError("先选择导演。")
    if active().intelligence.get("pending_plan"):
        raise RuntimeError("还有待应用修改，请先应用或放弃。")
    if SCENES and all(scene.get("prompt") and not scene.get("needs_rewrite") for scene in SCENES):
        return
    write_prompts(director_id, CHAT.get("messages") or [], 0, ratio)


def beat_scale_problem(chunk):
    found = re.search(r"景别", chunk)
    if not found:
        return ""
    tail = chunk[found.end():found.end() + 16]
    for word in ("特写", "全景", "近景", "中景", "远景"):
        if word in tail:
            return word
    for scale in sorted(SCALES, key=len, reverse=True):
        index = tail.find(scale)
        if index < 0:
            continue
        rest = tail[index + len(scale):index + len(scale) + 1]
        if scale == "特" and rest == "写":
            continue
        if scale == "中" and rest == "景":
            continue
        if scale == "近" and rest == "景":
            continue
        if scale == "远" and rest == "景":
            continue
        return ""
    return "不在规定的字里"


def beat_has_camera(chunk):
    if "运镜" in chunk:
        return True
    if "摄影机" not in chunk and "镜头" not in chunk:
        return False
    return any(word in chunk for word in ("推进", "拉远", "固定", "横移", "平移", "跟随", "跟拍", "上升", "下降", "移动", "后退", "摇", "绕", "俯", "仰", "急停", "不动", "贴", "从", "位于"))


def beat_has_state(chunk):
    if "人物状态" in chunk:
        return True
    if any(word in chunk for word in ("在画面", "向画面", "位于", "面朝", "身体朝", "朝向", "重心", "身体", "低位")):
        return True
    if "段尾" in chunk and any(word in chunk for word in ("停在", "仍在", "朝", "通过", "落在", "离开", "低于", "高于")):
        return True
    named = any((asset.get("name") or "") in chunk for asset in ASSETS if asset.get("kind") == "人物" and asset.get("name"))
    posture = any(word in chunk for word in ("胸口", "髋", "腰", "肩", "膝", "肘", "臂", "腿", "脚", "手", "头", "贴近", "压低", "弯曲", "伸直", "收拢", "翻转"))
    return named and posture


def beat_has_action(chunk):
    if "肢体动作" in chunk:
        return True
    parts = ("脚", "手", "爪", "膝", "肘", "肩", "腰", "臂", "腿", "枪")
    verbs = ("握", "蹬", "踩", "抬", "压", "伸", "弯", "落", "碰", "刺", "扫", "挪", "收", "送", "迈", "跨", "屈", "扭", "转", "提", "卡", "横")
    return any(part in chunk for part in parts) and any(verb in chunk for verb in verbs)


def beat_has_sound(chunk):
    if any(word in chunk for word in ("声", "鸣", "听见")):
        return True
    return "响" in chunk.replace("影响", "")


def beat_missing(chunk):
    missing = []
    if "环境" not in chunk:
        missing.append("环境")
    if "景别" not in chunk:
        missing.append("景别")
    if not beat_has_camera(chunk):
        missing.append("运镜")
    if not beat_has_state(chunk):
        missing.append("人物状态")
    if not beat_has_action(chunk):
        missing.append("肢体动作")
    if not beat_has_sound(chunk):
        missing.append("声音")
    return missing


def parsed_ranges(text):
    found = []
    for match in re.finditer(r"(\d+)\s*[-–—~到至]\s*(\d+)\s*(?:秒|s)", text or "", re.I):
        found.append((int(match.group(1)), int(match.group(2)), match.start()))
    return found


def timeline_problems(prompt, seconds):
    text = prompt or ""
    problems = []
    parsed = parsed_ranges(text)
    if not parsed:
        problems.append("没有连续的整秒时间段")
        return problems
    if parsed[0][0] != 0:
        problems.append("时间段不是从 0 秒开始")
    for index, (start, end, _pos) in enumerate(parsed):
        label = f"{start}-{end}秒"
        if end <= start:
            problems.append(label + " 这段时间反了")
            continue
        if index + 1 < len(parsed):
            nxt = parsed[index + 1][0]
            if nxt > end:
                problems.append(f"{end}秒到{nxt}秒 中间断了")
            elif nxt < end:
                problems.append(label + " 和下一段重叠")
    try:
        sec = int(seconds or 0)
    except (TypeError, ValueError):
        sec = 0
    if sec and parsed[-1][1] != sec:
        problems.append(f"时间段停在 {parsed[-1][1]} 秒，这场是 {sec} 秒")
    return problems


def timeline_lint_error(scenes):
    lines = []
    for index, scene in enumerate(scenes, start=1):
        problems = timeline_problems(scene.get("prompt") or "", scene.get("seconds"))
        if not problems:
            continue
        place = scene.get("place") or ""
        lines.append(f"第{index}场{place}：" + "；".join(problems))
    if not lines:
        return ""
    return "提示词的时间没接上，没有提交。" + " ".join(lines)


def field_lint_director():
    return (CHAT.get("director_id") or "") == "drama"


def lint_scene_prompt(prompt, seconds):
    text = prompt or ""
    problems = timeline_problems(prompt, seconds)
    parsed = parsed_ranges(text)
    if not parsed:
        missing = beat_missing(text)
        if missing:
            problems.append("缺" + "、".join(missing))
        return problems
    for index, (start, end, pos) in enumerate(parsed):
        if end <= start:
            continue
        label = f"{start}-{end}秒"
        end_pos = parsed[index + 1][2] if index + 1 < len(parsed) else len(text)
        chunk = text[pos:end_pos]
        missing = beat_missing(chunk)
        if missing:
            problems.append(label + " 缺" + "、".join(missing))
        bad_scale = beat_scale_problem(chunk)
        if bad_scale:
            problems.append(label + " 景别" + bad_scale)
    return problems


def prompt_lint_error(scenes):
    lines = []
    for index, scene in enumerate(scenes, start=1):
        problems = lint_scene_prompt(scene.get("prompt") or "", scene.get("seconds"))
        if not problems:
            continue
        place = scene.get("place") or ""
        lines.append(f"第{index}场{place}：" + "；".join(problems))
    if not lines:
        return ""
    return "提示词结构没过，没有提交，句子没有改。" + " ".join(lines)


def normalize_seconds_choice(value):
    raw = str(value or "auto").strip()
    if raw == "auto":
        return "auto"
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return "auto"
    if 4 <= number <= 30:
        return str(number)
    return "auto"


def seedance_seconds(scene_seconds, choice):
    selected = normalize_seconds_choice(choice)
    seconds = int(scene_seconds or 0) if selected == "auto" else int(selected)
    if not 4 <= seconds <= 30:
        raise RuntimeError("场景时长必须在4～30秒，请先确定分场时长。")
    return seconds


def start_episode(ratio, resolution, video_model="seedance", seconds_choice="auto"):
    if JOB.get("phase") == "running" or TASK["state"] in {"running", "paused", "stopping"}:
        raise RuntimeError("已有任务在进行，请等待完成。")
    if any(j.get("status") in {"unknown", "submitting"} for j in JOB.get("jobs") or []):
        raise RuntimeError("存在结果未知的提交，请先点核对队列，避免重复扣费。")
    MODE.update({"video": video_model, "seconds": normalize_seconds_choice(seconds_choice)})
    plan = INTELLIGENCE.preflight(ratio, resolution, video_model, seconds_choice)
    if not plan["ok"]:
        raise RuntimeError("提交前检查未通过：" + " ".join(plan["errors"]))
    task_begin("video", "逐场提交")
    old_jobs = list(JOB.get("jobs") or [])
    JOB.update({"phase": "running", "started": time.time(), "jobs": [], "film": "", "error": ""})
    jobs = JOB["jobs"]
    try:
        for index, scene in enumerate(SCENES, 1):
            if scene.get("disabled"):
                continue
            task_gate()
            approved = WORKFLOW.require("video", scene, {"ratio":ratio,"resolution":resolution,"video_model":video_model,"seconds_choice":seconds_choice})
            payload = INTELLIGENCE.payload(scene)
            payload["prompt"] = approved["prompt"]
            payload["reference_content"] = [(r['asset_id'],r['sha256']) for r in approved['references']]
            seconds = int(scene["seconds"]) if video_model == "h3" else seedance_seconds(scene["seconds"], seconds_choice)
            fingerprint = core.job_fingerprint(scene, payload, seconds, ratio, resolution, video_model, list(ASSETS))
            previous = next((j for j in old_jobs if j.get("fingerprint") == fingerprint and j.get("status") in {"queued", "done"} and (j.get("status") != "done" or Path(j.get("file") or "").is_file())), None)
            if previous:
                jobs.append(previous)
                save_session()
                continue
            prefix = f"prompt-desk/{CURRENT_ID['id']}/{scene['id']}_{uuid.uuid4().hex[:8]}"
            reservation = INTELLIGENCE.reserve("video", seconds, scene.get("place") or f"第{index}场", video_model, resolution)
            job = {"scene_id": scene["id"], "place": scene.get("place") or "", "seconds": seconds,
                "prompt_id": "", "status": "submitting", "file": "", "prompt": payload["prompt"],
                "source_prompt": scene["prompt"], "assets": payload["assets"], "audios": payload["audios"],
                "asset_ids": payload["asset_ids"], "ratio": ratio, "resolution": resolution, "prefix": prefix,
                "engine": video_model, "fingerprint": fingerprint, "reservation_id": reservation["id"]}
            jobs.append(job)
            save_session()  # Intent is durable before crossing the external boundary.
            try:
                WORKFLOW.require("video", scene, {"ratio":ratio,"resolution":resolution,"video_model":video_model,"seconds_choice":seconds_choice})
                if video_model == "h3":
                    result = submit_h3(job["prompt"], seconds, ratio, resolution, job["assets"], filename_prefix=prefix)
                else:
                    result = submit_comfy(job["prompt"], seconds, ratio, resolution, "doubao-seedance-2-5", job["assets"], job["audios"], filename_prefix=prefix)
                if not result.get("prompt_id"):
                    raise RuntimeError("接口没有返回任务ID，受理结果未知。")
            except Exception as exc:
                job.update({"status": "unknown", "error": str(exc)[:300]})
                INTELLIGENCE.finish_reservation(reservation, "unknown")
                raise RuntimeError("这一场提交结果未知，请核对队列后再决定重试。" + str(exc)) from exc
            job.update({"prompt_id": result["prompt_id"], "status": "queued"})
            INTELLIGENCE.finish_reservation(reservation, "accepted")
            task_label(f"第{index}/{len(SCENES)}场已受理")
            save_session()
    except Exception as exc:
        JOB.update({"phase": "error", "error": str(exc)[:500]})
        save_session()
        task_finish("video")
        raise
    save_session()
    spawn(watch_episode)
    return {"phase": JOB["phase"], "jobs": jobs}


def script_public():
    return {"name": SCRIPT["name"], "chars": len(SCRIPT["text"]), "scenes": len(SCENES)}


def script_beat_rule():
    return creation.profile(sys.modules[__name__])[1]


def system_prompt(director_id):
    item = director_by_id(director_id)
    if item is None: raise FileNotFoundError(director_id)
    name, rules = creation.profile(sys.modules[__name__])
    prompt = f"""你是{item[1]}题材的{name}导演，写可直接提交的最终中文视频提示词。
按统一项目经验、当前模型规则和用户已确认的要求创作。只写真正存在的参考素材，不杜撰对白、品牌或设定。
{rules}
每场单独输出下列标记，按指定场号与秒数，不能改场次：
<<<VIDEO>>>
场次：N
时长：本场整数秒
提示词：完整最终正文
<<<END>>>
不要把整集塞进一个标记。画幅、分辨率留在界面设置。讨论说明放在标记外。
"""
    if SCRIPT['text']: prompt += '\n用户剧本《' + SCRIPT['name'] + '》：\n' + SCRIPT['text']
    return prompt


def chat_prompt(director_id):
    item = director_by_id(director_id)
    if item is None:
        raise FileNotFoundError(director_id)
    prompt = f"""你是{item[1]}导演，正在和用户聊天。像同事一起把这支片子聊清楚。

用户说什么就接什么。可以一起想人物、情节、镜头，以及他还没想好的地方。用平常的中文说。几句能说清就几句，需要展开就展开。

这是聊天，不是填表。不要追问缺了哪一项。不要让用户按「观众必须看见哪一件」来回答。不要把某一类片子的固定节拍套上去。用户请求提示词时就在对话里写完整最终草稿。资产提示词进入素材区，视频提示词按真实分镜ID进入待采纳草稿。用户查看并确认全文、参考和规格后，生图或提交视频会直接提交，不会再次调用模型改词。缺词或确认过期时先提示用户，不自动补写。不要强制用户先出风格图。资产参考规格为21:9、1K，成片画幅由提交设置决定。

用户要新的一张，或同一只生物的另一种状态、另一张关系图，先用平常的话说明这张要认出什么。然后每一张另起标记，标记不会显示给用户。名称用这次新起的名字，不要改成文件夹里已有的名字。改已经有的那一张时，名称必须和文件夹里的名称完全一样。没点名的不要写：

<<<ASSET>>>
种类：人物
名称：
画面：
<<<END>>>

画面字段必须是可直接提交的完整最终生图提示词。要锁的长相、衣服、构图、背景、光线、材质和限制全部在这里写清；人物/道具需要白底或多视图时直接写入，程序不会再添加。两头比体型的关系图写明两头和位置。用户没确认的要求保持为建议。

用户最后一句话后面会附上资产文件夹里已经出好的图。每张前面有一行「资产图：种类／名称」。按这些画面说材质、光、颜色和外形，不要按文件名猜。用户另外上传的参考图会标成「用户上传的参考图」，那不是资产图。没有附上画面的那一张，不要说自己看过。
"""
    if SCRIPT["text"]:
        prompt += "\n用户上传过剧本《" + SCRIPT["name"] + "》。聊天时用到再提，不要把全文复述一遍。\n\n" + SCRIPT["text"]
    return prompt + INTELLIGENCE.chat_contract()


def call_model(messages):
    if not MODEL_LOCK.acquire(blocking=False):
        raise RuntimeError("上一份还在写。等它停下再点。")
    started = time.monotonic()
    paused_for = 0.0
    pause_mark = None
    while True:
        try:
            task_gate()
        except TaskStopped:
            MODEL_LOCK.release()
            raise
        outcome = {}

        model_work = active()
        def run(box=outcome):
            token = ACTIVE.set(model_work)
            try:
                box["value"] = _call_model(messages)
            except Exception as exc:
                box["error"] = exc
            finally:
                ACTIVE.reset(token)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        timed_out = False
        while worker.is_alive():
            worker.join(0.3)
            if TASK_STOP.is_set() or TASK.get("state") == "paused":
                kick_io()
            now = time.monotonic()
            if TASK.get("state") == "paused":
                if pause_mark is None:
                    pause_mark = now
            elif pause_mark is not None:
                paused_for += now - pause_mark
                pause_mark = None
            if TASK.get("state") != "paused" and now - started - paused_for > 600:
                kick_io()
                timed_out = True
                break
        if timed_out:
            def release_later():
                worker.join()
                MODEL_LOCK.release()

            spawn(release_later)
            raise RuntimeError("模型想得太久，已停下。等它停下再点。")
        err = outcome.get("error")
        if isinstance(err, TaskHeld):
            continue
        MODEL_LOCK.release()
        if err is not None:
            raise err
        return outcome.get("value") or ""


def _call_model(messages):
    messages = INTELLIGENCE.prepare(messages)
    cfg = load_config()
    cfg.setdefault("reasoning_effort", "xhigh")
    base = cfg["base_url"].rstrip("/")
    key = resolve_key(cfg)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    if base.endswith("/v1"):
        url = base + "/chat/completions"
        payload = {"model": cfg["model"], "messages": messages, "temperature": 0.4, "reasoning_effort": cfg["reasoning_effort"]}
    else:
        url = base + "/api/chat"
        payload = {"model": cfg["model"], "messages": messages, "stream": False, "options": {"temperature": 0.4, "reasoning_effort": cfg["reasoning_effort"]}}
    raw = json.dumps(payload).encode("utf-8")
    request = Request(url, data=raw, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=600) as response:
            close = bind_io(response)
            try:
                if TASK_STOP.is_set():
                    raise TaskStopped("已终止")
                if TASK.get("state") == "paused":
                    raise TaskHeld("已暂停")
                body = json.loads(response.read().decode("utf-8"))
            finally:
                unbind_io(close)
    except (TaskStopped, TaskHeld):
        raise
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        if key:
            detail = detail.replace(key, "***")
        raise RuntimeError(f"模型接口拒绝：{exc.code} {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        if TASK_STOP.is_set():
            raise TaskStopped("已终止") from exc
        if TASK.get("state") == "paused":
            raise TaskHeld("已暂停") from exc
        raise RuntimeError("模型想得太久，已停下。可以再点一次。") from None
    if "message" in body and isinstance(body["message"], dict):
        return body["message"].get("content") or ""
    choices = body.get("choices") or []
    if choices:
        return ((choices[0].get("message") or {}).get("content")) or ""
    raise RuntimeError("模型没有返回正文。")


def stream_reply(messages):
    while True:
        task_gate()
        try:
            return _stream_reply(messages)
        except TaskHeld:
            continue


def _stream_reply(messages):
    messages = INTELLIGENCE.prepare(messages)
    cfg = load_config()
    cfg.setdefault("reasoning_effort", "xhigh")
    base = cfg["base_url"].rstrip("/")
    key = resolve_key(cfg)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    if not base.endswith("/v1"):
        return _call_model(messages[1:])
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.4, "stream": True, "reasoning_effort": cfg["reasoning_effort"]}
    request = Request(base + "/chat/completions", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    collected = []
    reasoning = []
    started = time.monotonic()
    try:
        with urlopen(request, timeout=600) as response:
            close = bind_io(response)
            try:
                while True:
                    if TASK_STOP.is_set():
                        raise TaskStopped("已终止")
                    if TASK.get("state") == "paused":
                        raise TaskHeld("已暂停")
                    if time.monotonic() - started > 600:
                        break
                    line = response.readline()
                    if TASK_STOP.is_set():
                        raise TaskStopped("已终止")
                    if TASK.get("state") == "paused":
                        raise TaskHeld("已暂停")
                    if not line:
                        break
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    try:
                        obj = json.loads(data.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    delta = ((obj.get("choices") or [{}])[0].get("delta") or {})
                    thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    piece = delta.get("content") or ""
                    if thought:
                        reasoning.append(thought)
                        THINKING["text"] = "".join(reasoning)[-1200:]
                    if piece:
                        collected.append(piece)
                        THINKING["text"] = "".join(collected)
            finally:
                unbind_io(close)
    except (TaskStopped, TaskHeld):
        raise
    except HTTPError:
        if collected:
            return "".join(collected)
        return _call_model(messages[1:])
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        if TASK_STOP.is_set():
            raise TaskStopped("已终止") from exc
        if TASK.get("state") == "paused":
            raise TaskHeld("已暂停") from exc
        if collected:
            return "".join(collected)
        raise RuntimeError("模型想得太久，已停下。等它停下再发。") from None
    text = "".join(collected).strip()
    if text:
        return text
    if time.monotonic() - started > 20:
        raise RuntimeError("模型想得太久，已停下。等它停下再发。")
    return _call_model(messages[1:])


def preview_jpeg(path):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((768, 432))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=72, optimize=True)
        return buf.getvalue()


def image_content(raw):
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")},
    }


def vision_parts():
    parts = []
    shown = 0
    skipped = []
    relevant = {aid for scene in SCENES for aid in scene.get("asset_ids") or []}
    ordered = sorted(list(ASSETS), key=lambda a: (a.get("id") not in relevant, not a.get("needs_redraw")))
    for asset in ordered:
        if (asset.get("kind") or "") == "音频":
            continue
        filename = asset.get("file") or ""
        path = lib() / filename if filename else None
        if path is None or not path.is_file():
            continue
        label = f"{asset.get('kind') or '资产'}／{asset.get('name') or path.stem}"
        if shown >= 16:
            skipped.append(label)
            continue
        try:
            raw = preview_jpeg(path)
        except OSError:
            skipped.append(label)
            continue
        parts.append({"type": "text", "text": "资产图：" + label})
        parts.append(image_content(raw))
        shown += 1
    for ref in (REFS or [])[-4:]:
        path = ref_dir() / (ref.get("file") or "")
        if not path.is_file():
            continue
        try:
            raw = preview_jpeg(path)
        except OSError:
            continue
        parts.append({"type": "text", "text": "用户上传的参考图：" + (ref.get("name") or path.stem)})
        parts.append(image_content(raw))
    if skipped:
        parts.append({"type": "text", "text": "这几张资产图没有附上画面：" + "、".join(skipped)})
    return parts


def with_ref_images(messages):
    parts = vision_parts()
    if not parts:
        return messages
    copied = [{"role": item.get("role"), "content": item.get("content")} for item in messages]
    for index in range(len(copied) - 1, -1, -1):
        if copied[index].get("role") != "user":
            continue
        text = copied[index].get("content") or ""
        if not isinstance(text, str):
            break
        copied[index] = {"role": "user", "content": [{"type": "text", "text": text or "看这些图。"}] + parts}
        break
    return copied


def begin_reply(director_id, clean):
    if TASK["state"] in {"running", "paused", "stopping"} or THINKING.get("on"):
        raise RuntimeError("上一项任务还在进行。")
    CHAT["director_id"] = director_id
    CHAT["messages"] = core.merge_history(CHAT.get("messages") or [], clean)
    history = list(CHAT["messages"])
    THINKING.update({"on": True, "text": "正在理解要求"})
    task_begin("think", "理解要求")
    save_session()
    def work():
        try:
            raw = stream_reply([{"role": "system", "content": chat_prompt(director_id)}] + with_ref_images(history[-24:]))
            task_gate()
            raw = INTELLIGENCE.accept_reply(raw, history)
            # Asset marks may add new assets; editing an existing one requires an explicit plan.
            existing = {a.get("name") for a in ASSETS}
            new_names = [a["name"] for a in split_assets(raw) if a.get("name") not in existing]
            spoken = apply_asset_marks(raw, keep_files=True, only=new_names) if new_names else re.sub(r"<<<ASSET>>>.*?<<<END>>>", "", raw, flags=re.S)
            CHAT["messages"] = history + [{"role": "assistant", "content": (spoken or "我听到了。")[:16000]}]
        except TaskStopped:
            CHAT["messages"] = history + [{"role": "assistant", "content": "已终止。"}]
        except Exception as exc:
            CHAT["messages"] = history + [{"role": "assistant", "content": "这句没完成，可以重试。" + str(exc)[:180]}]
        finally:
            THINKING.update({"on": False, "text": ""})
            task_finish("think")
            save_session()
    spawn(work)


def parse_block(block):
    marker = "提示词："
    if marker in block:
        settings_text, prompt = block.split(marker, 1)
    else:
        settings_text, prompt = "", block
    prompt = prompt.strip()
    return {
        "settings": settings_text.strip(),
        "prompt": prompt,
        "warnings": warnings_for(prompt),
    }


def split_reply(text):
    matches = list(re.finditer(r"<<<(?:VIDEO|SEEDANCE)>>>(.*?)<<<END>>>", text, re.S))
    if not matches:
        return text.strip(), []
    talk = text[:matches[0].start()].strip()
    takes = []
    for match in matches:
        item = parse_block(match.group(1))
        if item["prompt"]:
            takes.append(item)
    return talk, takes


def warnings_for(prompt):
    if not prompt:
        return []
    found = []
    for word in BAD_SCALES:
        if word in prompt:
            found.append(f"提示词里写了「{word}」。景别只用：{'、'.join(SCALES)}。")
    if "观众看见" in prompt or "所以明白" in prompt:
        found.append("观众句进了提示词。请在确认前修改草稿，生成时会原样提交。")
    if re.search(r"720|1080|分辨率", prompt):
        found.append("分辨率写进了提示词正文。它只留在设置里。")
    return found


def check_model():
    cfg = load_config()
    base = cfg["base_url"].rstrip("/")
    key = resolve_key(cfg)
    url = base + ("/models" if base.endswith("/v1") else "/api/tags")
    headers = {"Authorization": "Bearer " + key} if key else {}
    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=8) as response:
            ok = 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        ok = False
    return {"ok": ok, "base_url": cfg["base_url"], "model": cfg["model"], "has_key": bool(key)}


def safe_filename(name):
    base = str(name or "asset").replace("\\", "_").replace("/", "_")
    base = Path(base).name
    base = re.sub(r"[^\w.\- \u4e00-\u9fff]", "_", base).strip("._")
    return (base or "asset")[:80]


def list_assets():
    if not CURRENT_ID.get("id"):
        return []
    lib().mkdir(exist_ok=True)
    rows = []
    for path in sorted(lib().iterdir(), key=lambda item: item.name):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        rows.append({"name": path.name, "bytes": path.stat().st_size})
    return rows


def store_ref(name, raw):
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("单张参考图不要超过 15MB")
    filename = safe_filename(name)
    if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        filename += ".png"
    dest = ref_dir() / filename
    dest.write_bytes(raw)
    stem = Path(filename).stem
    REFS.append({"name": stem, "file": dest.name})
    save_session()
    return {"name": stem, "file": dest.name, "refs": list(REFS)}


def place_asset(kind, name, raw):
    if kind not in {"人物", "场景", "道具", "音频"}:
        raise ValueError("资产只分人物、场景、道具、音频")
    filename = safe_filename(name)
    suffix = Path(filename).suffix.lower()
    if kind == "音频":
        if suffix not in {".mp3", ".wav", ".m4a"}:
            raise ValueError("音频只收 mp3、wav、m4a")
        if len(raw) > 20 * 1024 * 1024:
            raise ValueError("一段音频不要超过 20MB")
    else:
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("图片只收 png、jpg、webp")
        if len(raw) > 15 * 1024 * 1024:
            raise ValueError("单张图不要超过 15MB")
    stem = Path(filename).stem
    replacing = any(
        asset.get("kind") == kind and asset.get("file") and (
            asset.get("name") == stem or (asset.get("name") and (asset["name"] in stem or stem in asset["name"]))
        )
        for asset in ASSETS
    )
    if kind == "音频":
        have = sum(1 for asset in ASSETS if asset.get("kind") == "音频" and asset.get("file"))
        if have >= 10 and not replacing:
            raise ValueError("音频最多 10 段")
    elif not replacing and len(list_assets()) >= 50:
        raise ValueError("图库最多 50 张")
    dest = lib() / filename
    dest.write_bytes(raw)
    matches = [
        asset for asset in ASSETS
        if asset.get("kind") == kind and asset.get("name") and (asset["name"] == stem or asset["name"] in stem or stem in asset["name"])
    ]
    target = next((asset for asset in matches if not asset.get("file")), None) or (matches[0] if matches else None)
    if target:
        target["file"] = dest.name
    else:
        ASSETS.append({"kind": kind, "name": stem, "picture": "", "file": dest.name})
    save_session()
    return {"assets": list(ASSETS)}


def store_asset(name, raw):
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("单张图不要超过 15MB")
    filename = safe_filename(name)
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("资产只收 png、jpg、webp")
    lib().mkdir(exist_ok=True)
    dest = lib() / filename
    if not dest.exists() and len(list_assets()) >= 50:
        raise ValueError("图库最多 50 张")
    dest.write_bytes(raw)
    return {"name": dest.name, "bytes": dest.stat().st_size}


def remove_asset(name):
    filename = safe_filename(name or "")
    if not filename:
        raise RuntimeError("没有这张图。")
    root = lib().resolve()
    target = (root / filename).resolve()
    if target.parent != root:
        raise RuntimeError("没有这张图。")
    if target.is_file():
        target.unlink()
    kept = []
    for asset in ASSETS:
        if asset.get("file") != filename:
            kept.append(asset)
            continue
        if (asset.get("picture") or "").strip():
            item = dict(asset)
            item["file"] = ""
            kept.append(item)
    ASSETS.clear()
    ASSETS.extend(kept)
    save_session()
    return {"assets": list(ASSETS)}


def task_public():
    return {
        "state": TASK.get("state") or "idle",
        "kind": TASK.get("kind") or "",
        "label": TASK.get("label") or "",
        "pending_plan": bool(active().intelligence.get("pending_plan")),
        "review_count": len(active().intelligence.get("reviews") or []),
    }


def task_begin(kind, label):
    with TASK_LOCK:
        if TASK["state"] in {"running", "paused", "stopping"}:
            raise RuntimeError("已经有任务在进行。先暂停或终止。")
        TASK_STOP.clear()
        TASK_GO.set()
        TASK.update({"state": "running", "kind": kind, "label": label or "", "mark": ""})


def task_finish(kind):
    with TASK_LOCK:
        if TASK.get("kind") != kind:
            return
        TASK.update({"state": "idle", "kind": "", "label": "", "mark": ""})
        TASK_STOP.clear()
        TASK_GO.set()
        LIVE_IO["close"] = None


def task_label(text):
    if TASK.get("state") in {"running", "paused", "stopping"}:
        TASK["label"] = text or ""


def task_gate():
    while True:
        if TASK_STOP.is_set():
            raise TaskStopped("已终止")
        if TASK.get("state") != "paused":
            return
        TASK_GO.wait(0.3)


def kick_io():
    close = LIVE_IO.get("close")
    if not close:
        return
    try:
        close()
    except OSError:
        return


def bind_io(response):
    def close(resp=response):
        try:
            resp.close()
        except OSError:
            return

    LIVE_IO["close"] = close
    return close


def unbind_io(close):
    if LIVE_IO.get("close") == close:
        LIVE_IO["close"] = None


def comfy_post(path, payload):
    request = Request(
        comfy_base() + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            response.read()
    except (HTTPError, URLError, TimeoutError, OSError):
        return


def hold_video_jobs():
    # Pausing local scheduling does not cancel provider-accepted jobs.
    return


def release_video_jobs():
    # Resume monitoring the original IDs; never blindly resubmit on resume.
    return


def comfy_queue():
    try:
        with urlopen(comfy_base() + "/queue", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def comfy_stop_own():
    ids = []
    for job in JOB.get("jobs") or []:
        prompt_id = str(job.get("prompt_id") or "")
        if not prompt_id or job.get("file") or job.get("status") in {"done", "error"}:
            continue
        ids.append(prompt_id)
    if not ids:
        return
    running = []
    for item in comfy_queue().get("queue_running") or []:
        if isinstance(item, list) and len(item) > 1:
            running.append(str(item[1]))
    if any(prompt_id in ids for prompt_id in running):
        comfy_post("/interrupt", {})
    comfy_post("/queue", {"delete": ids})


def task_pause():
    with TASK_LOCK:
        if TASK["state"] != "running":
            raise RuntimeError("现在没有在跑的任务。")
        TASK["state"] = "paused"
        TASK_GO.clear()
        if TASK["kind"] == "draw" and DRAWING.get("on"):
            TASK["mark"] = DRAWING.get("phase") or "draw"
            DRAWING["phase"] = "paused"
        if TASK["kind"] == "style" and STYLE.get("phase") == "plate":
            STYLE["phase"] = "paused"
        if TASK["kind"] == "think":
            THINKING["text"] = "已暂停"
    hold_video_jobs()
    kick_io()
    if TASK.get("kind") != "video":
        comfy_stop_own()
    save_session()
    return task_public()


def task_resume():
    with TASK_LOCK:
        if TASK["state"] != "paused":
            raise RuntimeError("现在没有暂停的任务。")
        kind = TASK["kind"]
    if kind == "video":
        release_video_jobs()
    with TASK_LOCK:
        if TASK["state"] != "paused" or TASK["kind"] != kind:
            return task_public()
        TASK["state"] = "running"
        if kind == "draw" and DRAWING.get("on"):
            DRAWING["phase"] = TASK.get("mark") or "draw"
        if kind == "style" and STYLE.get("phase") == "paused":
            STYLE["phase"] = "plate"
        TASK_GO.set()
    save_session()
    return task_public()


def task_halt():
    with TASK_LOCK:
        if TASK["state"] not in {"running", "paused"}:
            raise RuntimeError("现在没有在进行的任务。")
        TASK["state"] = "stopping"
        TASK["label"] = "正在终止"
        TASK_STOP.set()
        TASK_GO.set()
        if TASK["kind"] == "video":
            for job in JOB.get("jobs") or []:
                if not job.get("file") and job.get("status") not in {"done", "error"}:
                    job["status"] = "held"
    kick_io()
    comfy_stop_own()
    save_session()
    return task_public()


def generate_sheet(banana, picture, dest, **kwargs):
    if active().intelligence.get("pending_plan"):
        raise RuntimeError("先应用或放弃待处理修改，再生成图片。")
    # Approved prompts already include the director's drafting decisions; never append creative text here.
    approved = kwargs.pop("approved", False)
    if not approved:
        picture = INTELLIGENCE.context() + "\n【本次只生成静态参考图】\n" + picture
    reservation = INTELLIGENCE.reserve("image", 1, Path(dest).name)
    try:
        task_gate()
        if approved:
            from jiji_images import generate_approved
            result = generate_approved(banana,picture,dest,**kwargs)
        else:
            result = banana.generate_image(picture, dest, **kwargs)
    except Exception:
        # A timeout may have consumed provider credit; retain the estimated reservation.
        INTELLIGENCE.finish_reservation(reservation, "unknown")
        raise
    INTELLIGENCE.finish_reservation(reservation, "accepted")
    return result


def comfy_base():
    return load_config()["comfy_url"].rstrip("/")


def comfy_status():
    url = comfy_base() + "/system_stats"
    try:
        with urlopen(url, timeout=2) as response:
            ok = 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        ok = False
    return {"ok": ok, "url": comfy_base()}


def upload_to_comfy(path):
    boundary = uuid.uuid4().hex
    data = path.read_bytes()
    kind = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
        f"Content-Type: {kind}\r\n\r\n"
    ).encode() + data + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue'
        f"\r\n--{boundary}--\r\n"
    ).encode()
    request = Request(
        comfy_base() + "/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        meta = json.loads(response.read().decode("utf-8"))
    return meta.get("name") or path.name


H3_STEPS = 25
H3_FPS = 24.0


def dock_pixels(ratio, resolution):
    height = {"480p": 480, "720p": 720, "1080p": 1080}.get(resolution)
    parts = str(ratio or "").split(":")
    if height is None or len(parts) != 2:
        return None
    try:
        wide, tall = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if wide <= 0 or tall <= 0:
        return None
    if wide >= tall:
        pixels_h = height
        pixels_w = int(round(pixels_h * wide / tall))
    else:
        pixels_w = height
        pixels_h = int(round(pixels_w * tall / wide))
    return pixels_w, pixels_h


def h3_frame_count(seconds):
    count = max(5, int(round(float(seconds) * H3_FPS)))
    remain = (5 - (count % 17)) % 17
    return count + remain


def snap_up_32(value):
    value = int(value)
    if value % 32 == 0:
        return value
    return ((value + 31) // 32) * 32


def h3_canvas(ratio, resolution):
    pixels = dock_pixels(ratio, resolution)
    if pixels is None:
        return None
    width, height = pixels
    if resolution == "720p":
        return snap_up_32(width), snap_up_32(height)
    if width % 32 or height % 32:
        return None
    return width, height


def h3_seconds(seconds):
    frames = h3_frame_count(seconds)
    return frames, round(frames / H3_FPS, 1)


def h3_blockers(seconds, ratio, resolution):
    del seconds
    if h3_canvas(ratio, resolution) is None:
        pixels = dock_pixels(ratio, resolution)
        if pixels is None:
            return [f"H3 没有 {ratio} {resolution} 这一档。没有改分辨率，没有提交。"]
        width, height = pixels
        return [
            f"H3 画布必须是 32 的倍数。{ratio} {resolution} 是 {width}×{height}，对不上。"
            "720p 会改成 736 那一档。这一档没有改，没有提交。"
        ]
    return []


def h3_task_label(key):
    try:
        with urlopen(comfy_base() + "/object_info/MiniMaxH3Director", timeout=20) as response:
            info = json.loads(response.read().decode("utf-8"))
        labels = info["MiniMaxH3Director"]["input"]["required"]["task_type"][0]
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, IndexError) as exc:
        raise RuntimeError(f"H3 节点没有读到。没有提交。{exc}") from exc
    for label in labels:
        if str(label).split(" ", 1)[0] == key:
            return label
    raise RuntimeError(f"H3 没有 {key} 这一档。没有提交。")


def h3_timeline(prompt, frames, seconds, width, height):
    return json.dumps({
        "version": 4,
        "editMode": "global",
        "timelineMode": "gen_blank",
        "totalFrames": frames,
        "frameRate": H3_FPS,
        "width": width,
        "height": height,
        "refMaxSize": 2048,
        "output": {
            "mode": "fixed",
            "longEdge": width,
            "width": width,
            "height": height,
            "maxExportFrames": 0,
            "exportMode": "all",
            "continuityEnabled": False,
            "continuityOverlapFrames": 22,
        },
        "videoClips": [],
        "video": {
            "fileName": "",
            "videoFile": "",
            "subfolder": "",
            "type": "input",
            "frames": [],
            "frameMap": [],
        },
        "global": {
            "taskType": "",
            "prompt": prompt,
            "refs": [],
            "referenceVideo": {},
            "continuousReference": False,
            "genImage": {"imageFile": ""},
        },
        "segments": [{
            "id": "s0",
            "start": 0,
            "length": frames,
            "frameCount": frames,
            "durationSec": seconds,
            "prompt": "",
            "taskType": "",
            "refs": [],
            "referenceVideo": {},
            "genImage": {"imageFile": ""},
            "negativePrompt": "",
        }],
        "gen": {"defaultFrameCount": frames},
        "runSelectEnabled": False,
        "runSelection": [],
    }, ensure_ascii=False)


def video_prompt(text):
    return str(text or "")

def submit_h3(prompt, seconds, ratio, resolution, asset_names, filename_prefix="prompt-desk/h1"):
    if not comfy_status()["ok"]:
        raise RuntimeError("ComfyUI 没开。先打开本机 ComfyUI，端口 8189。")
    text = video_prompt(prompt)
    if not text:
        raise RuntimeError("先在提示词里选定一条，再提交。")
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 0
    blocked = h3_blockers(seconds, ratio, resolution)
    if blocked:
        raise RuntimeError(" ".join(blocked))
    width, height = h3_canvas(ratio, resolution)
    frames, seconds = h3_seconds(seconds)
    names = []
    for name in list(asset_names)[:9]:
        path = lib() / safe_filename(name)
        if path.is_file() and name not in names:
            names.append(name)
    task = h3_task_label("r2v" if names else "t2v")
    unet = (
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
        if names else
        "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    )
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "type": "minimax",
            "device": "default",
        }},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
    }
    node = 10
    if names:
        links = {}
        for name in names:
            remote = upload_to_comfy(lib() / safe_filename(name))
            graph[str(node)] = {"class_type": "LoadImage", "inputs": {"image": remote}}
            links[f"ref_image_{len(links)}"] = [str(node), 0]
            node += 1
        graph[str(node)] = {"class_type": "MiniMaxH3DirectorGroupReferenceToVideo", "inputs": {
            "prompt": text,
            "duration_sec": float(seconds),
            "ref_images": links,
        }}
        group_port = "r2v_groups"
    else:
        graph[str(node)] = {"class_type": "MiniMaxH3DirectorGroupImageToVideo", "inputs": {
            "prompt": text,
            "duration_sec": float(seconds),
        }}
        group_port = "i2v_groups"
    group_id = str(node)
    graph["6"] = {"class_type": "MiniMaxH3Director", "inputs": {
        "model": ["1", 0],
        "video_vae": ["3", 0],
        "audio_vae": ["4", 0],
        "clip": ["2", 0],
        group_port: [group_id, 0],
        "task_type": task,
        "global_prompt": text,
        "bd_grp_sample": "采样设置",
        "cfg": 1.0,
        "seed": 51000 + frames,
        "frame_rate": H3_FPS,
        "width": width,
        "height": height,
        "ref_max_size": 2048,
        "total_frames": frames,
        "timeline_data": h3_timeline(text, frames, seconds, width, height),
        "bd_grp_advanced": "高级采样",
        "steps": H3_STEPS,
        "sampler": "res_multistep",
        "scheduler": "beta",
        "shift_video": 12.0,
        "shift_audio": 3.0,
        "bd_grp_perf": "性能",
        "clear_vram_between_segments": True,
        "export_source_images": False,
    }}
    graph["7"] = {"class_type": "CreateVideo", "inputs": {
        "images": ["6", 0],
        "fps": ["6", 2],
        "audio": ["6", 1],
        "bit_depth": 8,
    }}
    graph["8"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["7", 0],
        "filename_prefix": filename_prefix,
        "format": "auto",
        "codec": "auto",
    }}
    payload = json.dumps({"prompt": graph, "client_id": "prompt-desk"}).encode("utf-8")
    request = Request(
        comfy_base() + "/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"ComfyUI 拒绝了：{exc.code} {detail}") from exc
    return {
        "prompt_id": body.get("prompt_id") or "",
        "seconds": seconds,
        "ratio": ratio,
        "resolution": resolution,
        "model": "h3",
        "steps": H3_STEPS,
    }


def submit_comfy(prompt, seconds, ratio, resolution, model, asset_names, audio_names=None, filename_prefix="prompt-desk/sd25"):
    if not comfy_status()["ok"]:
        raise RuntimeError("ComfyUI 没开。先打开本机 ComfyUI，端口 8189。")
    text = video_prompt(prompt)
    if not text:
        raise RuntimeError("先在提示词里选定一条，再提交。")
    asset_names = list(asset_names)[:10]
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 15
    if seconds < 4 or seconds > 30:
        raise RuntimeError("提交时长只能是 4 到 30 秒。")
    if resolution not in {"480p", "720p", "1080p"}:
        raise RuntimeError("分辨率只能是 480p、720p、1080p。")
    if ratio not in {"16:9", "9:16", "1:1", "21:9"}:
        ratio = "16:9"
    graph = {
        "1": {
            "class_type": "LimAPISeedanceGenerate",
            "inputs": {
                "prompt": text,
                "model": "doubao-seedance-2-5",
                "duration": seconds,
                "resolution": resolution,
                "ratio": ratio,
                "generate_audio": True,
                "watermark": False,
                "filename_prefix": filename_prefix,
                "poll_seconds": 8,
                "timeout": 900,
                "omni_task": "auto",
            },
        }
    }
    uploaded = []
    pack_inputs = {}
    for index, name in enumerate(asset_names, start=1):
        path = lib() / safe_filename(name)
        if not path.is_file():
            continue
        remote = upload_to_comfy(path)
        node_id = str(10 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": remote}}
        pack_inputs[f"image_{index}"] = [node_id, 0]
        uploaded.append(remote)
    if pack_inputs:
        graph["2"] = {"class_type": "SeedanceRefPack", "inputs": pack_inputs}
        graph["1"]["inputs"]["refs"] = ["2", 0]
    audio_inputs = {}
    for index, name in enumerate(audio_names or [], start=1):
        path = lib() / safe_filename(name)
        if not path.is_file():
            continue
        remote = upload_to_comfy(path)
        node_id = str(50 + index)
        graph[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": remote}}
        audio_inputs[f"audio_{index}"] = [node_id, 0]
    if audio_inputs:
        graph["3"] = {"class_type": "SeedanceAudioPack", "inputs": audio_inputs}
        graph["1"]["inputs"]["audios"] = ["3", 0]
    payload = json.dumps({"prompt": graph, "client_id": "prompt-desk"}).encode("utf-8")
    request = Request(
        comfy_base() + "/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"ComfyUI 拒绝了：{exc.code} {detail}") from exc
    return {
        "prompt_id": body.get("prompt_id") or "",
        "uploaded": uploaded,
        "seconds": seconds,
        "ratio": ratio,
        "resolution": resolution,
        "model": "doubao-seedance-2-5",
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def send_mp4(self, path, attachment=False):
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        if not attachment:
            header = self.headers.get("Range") or ""
            if header.startswith("bytes="):
                spec = header[6:].split(",", 1)[0]
                left, _, right = spec.partition("-")
                try:
                    if left:
                        start = int(left)
                    if right:
                        end = int(right)
                except ValueError:
                    start, end = 0, size - 1
                if start < 0 or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if attachment:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name))
        self.end_headers()
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("请求长度无效。")
        if length < 0 or length > 64 * 1024 * 1024:
            raise ValueError("上传大小不能超过64MB。")
        if length == 0:
            return {}
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求必须是JSON对象。")
        return data

    def bind_desk(self, claim_hold=True):
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        lan_enabled = BIND not in {"127.0.0.1", "::1", "localhost"}
        if not lan_enabled and host not in {"127.0.0.1", "localhost"}:
            self.desk_client = ""
            self.desk_error = "仅允许本机访问。"
            ACTIVE.set(BENCH)
            return
        self.desk_client = (self.headers.get("X-Desk-Client") or "").strip()[:80]
        self.desk_error = ""
        pid = (self.headers.get("X-Desk-Project") or "").strip()
        if "?" in self.path:
            query = parse_qs(self.path.split("?", 1)[1])
            if not pid and query.get("project"):
                pid = str(query.get("project")[0] or "").strip()
        if pid and not re.fullmatch(r"[\w\-]+", pid):
            pid = ""
        if not pid:
            ACTIVE.set(BENCH)
            return
        if claim_hold:
            try:
                claim(pid, self.desk_client)
            except RuntimeError as exc:
                self.desk_error = str(exc)
                ACTIVE.set(BENCH)
                return
        ACTIVE.set(work_for(pid))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        static = path in ("/", "/index.html", "/film", "/intelligence.js", "/journey.js", "/journey.css") or path.startswith(("/fonts/", "/library/", "/refs/", "/covers/", "/review-frames/", "/source-video-frames/"))
        self.bind_desk(claim_hold=not static)
        if self.desk_error and (self.desk_error == "仅允许本机访问。" or (not static and path != "/api/projects")):
            self.send_json(409, {"error": self.desk_error})
            return
        if path in ("/", "/index.html"):
            raw = WEB.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/fonts/"):
            name = safe_filename(unquote(path[len("/fonts/"):]))
            root = (WEB.parent / "fonts").resolve()
            file = (root / name).resolve()
            if file.parent != root or not file.is_file():
                self.send_json(404, {"error": "没有这套字"})
                return
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "font/ttf")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            return
        if path == "/api/directors":
            self.send_json(200, {"directors": public_directors()})
            return
        if path == "/api/health":
            self.send_json(200, check_model())
            return
        if path in {"/intelligence.js", "/journey.js", "/journey.css"}:
            raw = (ROOT / "web" / path[1:]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ("text/css" if path.endswith(".css") else "application/javascript") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/source-video-frames/"):
            parts = path.split("/")
            row = next((v for v in WORKFLOW.videos() if len(parts)==4 and v["id"]==parts[2]),None)
            name = unquote(parts[-1])
            if not row or not any(f["file"]==name for f in row.get("frames",[])):
                self.send_json(404,{"error":"关键帧不存在。"}); return
            file = project_dir()/"source-videos"/row["id"]/name
            if not file.is_file():
                self.send_json(404,{"error":"关键帧文件缺失。"}); return
            raw=file.read_bytes()
            self.send_response(200); self.send_header("Content-Type","image/jpeg")
            self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path.startswith("/review-frames/"):
            name = safe_filename(unquote(path[len("/review-frames/"):]))
            file = project_dir() / "reviews" / name
            if file.suffix.lower() != ".jpg" or not file.is_file():
                self.send_json(404, {"error": "没有这张检查帧。"})
                return
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/api/task":
            self.send_json(200, task_public())
            return
        if path == "/api/settings":
            cfg = load_config()
            self.send_json(200, {
                "base_url": cfg["base_url"],
                "model": cfg["model"],
                "has_key": bool(resolve_key(cfg)),
                "comfy_url": cfg.get("comfy_url") or "http://127.0.0.1:8188",
            })
            return
        if path == "/api/script":
            self.send_json(200, script_public())
            return
        if path == "/api/session":
            self.send_json(200, session_public())
            return
        if path == "/api/projects":
            self.send_json(200, projects_public())
            return
        if path == "/api/scenes":
            self.send_json(200, {"scenes": SCENES, "assets": ASSETS})
            return
        if path == "/api/episode":
            ready = film_file()
            self.send_json(200, {
                "phase": JOB["phase"],
                "jobs": JOB["jobs"],
                "film": JOB["film"],
                "film_ready": bool(ready),
                "error": JOB["error"],
                "started": JOB.get("started") or 0,
            })
            return
        if path == "/film":
            ready = film_file()
            if ready is None:
                self.send_json(404, {"error": "成片还没有"})
                return
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            self.send_mp4(ready, attachment="save=1" in query)
            return
        if path == "/api/assets":
            self.send_json(200, {"assets": list_assets()})
            return
        if path == "/api/comfy":
            self.send_json(200, comfy_status())
            return
        if path.startswith("/library/"):
            name = safe_filename(unquote(path[len("/library/"):]))
            file = lib() / name
            if not file.is_file():
                self.send_json(404, {"error": "没有这张图"})
                return
            raw = file.read_bytes()
            kind = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
            if file.suffix.lower() == ".webp":
                kind = "image/webp"
            if file.suffix.lower() == ".mp3":
                kind = "audio/mpeg"
            if file.suffix.lower() == ".wav":
                kind = "audio/wav"
            if file.suffix.lower() == ".m4a":
                kind = "audio/mp4"
            stat = file.stat()
            tag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            if (self.headers.get("If-None-Match") or "") == tag:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/refs/"):
            name = safe_filename(unquote(path[len("/refs/"):]))
            file = ref_dir() / name
            if not file.is_file():
                self.send_json(404, {"error": "没有这张参考图"})
                return
            raw = file.read_bytes()
            kind = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
            if file.suffix.lower() == ".webp":
                kind = "image/webp"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/covers/"):
            pid = safe_filename(unquote(path[len("/covers/"):]))
            file = auto_cover(pid)
            if not file:
                self.send_json(404, {"error": "没有封面"})
                return
            raw = file.read_bytes()
            kind = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
            if file.suffix.lower() == ".webp":
                kind = "image/webp"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_json(404, {"error": "没有这一页"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        origin = self.headers.get("Origin")
        if origin:
            origin_host = (urlsplit(origin).hostname or "").lower()
            request_host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
            if origin_host not in {"127.0.0.1", "localhost", request_host}:
                self.send_json(403, {"error": "请求来源不受信任。"})
                return
        self.bind_desk()
        if self.desk_error and (self.desk_error == "仅允许本机访问。" or path not in ("/api/projects", "/api/projects/open", "/api/projects/delete")):
            self.send_json(409, {"error": self.desk_error})
            return
        if path == "/api/source-video/upload":
            try:
                if not CURRENT_ID.get("id"): raise RuntimeError("先打开一个项目。")
                name = parse_qs(self.path.split("?",1)[-1]).get("name",[""])[0]
                self.connection.settimeout(120)
                result = WORKFLOW.upload_video(name,self.rfile,int(self.headers.get("Content-Length") or 0))
                self.send_json(200,result)
            except (RuntimeError,ValueError,OSError) as exc:
                self.close_connection = True
                self.send_json(400,{"error":str(exc)})
            return
        try:
            data = self.read_json()
        except (ValueError, UnicodeError):
            self.send_json(400, {"error": "请求必须是有效JSON对象，且不超过64MB。"})
            return
        if path.startswith(("/api/creation", "/api/prompt-", "/api/source-video/", "/api/assets/prompts", "/api/director-draft/")):
            try:
                if not CURRENT_ID.get("id"): raise RuntimeError("先打开一个项目。")
                self.send_json(200,WORKFLOW.handle(path,data))
            except (RuntimeError,ValueError,TypeError) as exc:
                self.send_json(400,{"error":str(exc)})
            return
        if path.startswith(("/api/intelligence", "/api/preflight", "/api/draw-plan", "/api/plan/", "/api/revisions/", "/api/scenes/edit", "/api/memory", "/api/budget", "/api/feedback", "/api/preferences/", "/api/jobs/", "/api/review")):
            try:
                self.send_json(200, INTELLIGENCE.handle(path, data))
            except (RuntimeError, ValueError, TypeError) as exc:
                self.send_json(400, {"error": str(exc)})
            return
        if path == "/api/reconcile":
            try:
                self.send_json(200, reconcile_jobs())
            except RuntimeError as exc:
                self.send_json(400, {"error": str(exc)})
            return
        if data.get("director_id") and path in {"/api/scenes", "/api/assets/all", "/api/prompts", "/api/style/find", "/api/stills"}:
            if director_by_id(data["director_id"]) is None:
                self.send_json(400, {"error": "导演不存在。"})
                return
            if TASK.get("state") != "idle":
                self.send_json(409, {"error": "等当前任务结束后再开始。"})
                return
            CHAT["director_id"] = data["director_id"]
        if path == "/api/task":
            action = str(data.get("action") or "")
            try:
                if action == "pause":
                    result = task_pause()
                elif action == "resume":
                    result = task_resume()
                elif action == "stop":
                    result = task_halt()
                else:
                    self.send_json(400, {"error": "要暂停、继续或终止。"})
                    return
            except RuntimeError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, result)
            return
        if path == "/api/settings":
            cfg = save_config(data)
            self.send_json(200, {"base_url": cfg["base_url"], "model": cfg["model"], "has_key": bool(cfg.get("api_key"))})
            return
        if path == "/api/session":
            try: update_chat(data)
            except RuntimeError as exc:
                self.send_json(409, {"error": str(exc)}); return
            self.send_json(200, session_public())
            return
        if path == "/api/projects":
            try:
                created = create_project(data.get("name") or "", self.desk_client)
            except RuntimeError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, {"project": created, **projects_public(), **session_public()})
            return
        if path == "/api/projects/open":
            try:
                open_project(str(data.get("id") or ""), self.desk_client)
            except RuntimeError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, {**projects_public(), **session_public()})
            return
        if path == "/api/projects/delete":
            try:
                left = delete_project(str(data.get("id") or ""), self.desk_client)
            except RuntimeError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, left)
            return
        if path == "/api/refs":
            name = str(data.get("name") or "")
            try:
                raw = base64.b64decode(data.get("data_base64") or "", validate=True)
                saved = store_ref(name, raw)
            except (ValueError, base64.binascii.Error):
                self.send_json(400, {"error": "这张参考图存不上"})
                return
            self.send_json(200, saved)
            return
        if path == "/api/script":
            if data.get("clear"):
                SCRIPT["name"] = ""
                SCRIPT["text"] = ""
                SCENES.clear()
                ASSETS.clear()
                JOB.update({"phase": "idle", "jobs": [], "film": "", "error": ""})
                CHAT["messages"] = []
                CHAT["step"] = "director"
                save_session()
                self.send_json(200, script_public())
                return
            name = str(data.get("name") or "")
            encoded = data.get("data_base64") or ""
            if TASK.get("state") != "idle" or SCENES or ASSETS:
                self.send_json(409, {"error": "当前项目已有任务、分镜或素材，请新建项目上传文件，或与导演讨论修改。"})
                return
            try:
                raw = base64.b64decode(encoded, validate=True)
                saved = store_script(name, raw)
            except (ValueError, base64.binascii.Error) as exc:
                self.send_json(400, {"error": str(exc) or "这份剧本读不了"})
                return
            except Exception as exc:
                self.send_json(400, {"error": "这份剧本读不了"})
                return
            self.send_json(200, saved)
            return
        if path == "/api/scenes":
            director_id = data.get("director_id") or ""
            if director_by_id(director_id) is None:
                self.send_json(400, {"error": "先选一位导演，再分场。"})
                return
            try:
                plan = classify_scenes(director_id)
            except (FileNotFoundError, RuntimeError) as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, plan)
            return
        if path == "/api/style/find":
            use_sheet_model(str(data.get("image_model") or MODE.get("image") or "banana"))
            try:
                style = find_style(data.get("director_id") or "")
            except (FileNotFoundError, RuntimeError) as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, {"style": style})
            return
        if path == "/api/style/upload":
            name = str(data.get("name") or "")
            try:
                raw = base64.b64decode(data.get("data_base64") or "", validate=True)
                style = add_style_upload(name, raw)
            except (ValueError, base64.binascii.Error) as exc:
                self.send_json(400, {"error": str(exc) or "这张风格图存不上"})
                return
            self.send_json(200, {"style": style})
            return
        if path == "/api/style/confirm":
            try:
                style = confirm_style(data.get("file") or "", data.get("files"))
            except RuntimeError as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, {"style": style})
            return
        if path == "/api/assets/all":
            try:
                result = make_all_assets(
                    data.get("director_id") or "",
                    str(data.get("ratio") or "16:9"),
                    str(data.get("image_model") or "banana"),
                    data.get("plan_fingerprint"),
                )
            except (FileNotFoundError, RuntimeError) as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, result)
            return
        if path == "/api/prompts":
            episode = data.get("episode") or ""
            try:
                episode = int(episode) if str(episode).strip() else 0
            except (TypeError, ValueError):
                episode = 0
            try:
                result = write_prompts(
                    data.get("director_id") or "",
                    data.get("messages") or [],
                    episode,
                    str(data.get("ratio") or "16:9"),
                )
            except (FileNotFoundError, RuntimeError) as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, result)
            return
        if path == "/api/episode":
            try:
                checked = INTELLIGENCE.preflight(str(data.get("ratio") or "16:9"), str(data.get("resolution") or "720p"), str(data.get("video_model") or "seedance"), str(data.get("seconds_choice") or "auto"))
                if checked["fingerprint"] != data.get("preflight_fingerprint"):
                    raise RuntimeError("项目在预览后发生变化，请重新检查再提交。")
                result = start_episode(
                    str(data.get("ratio") or "16:9"),
                    str(data.get("resolution") or "720p"),
                    str(data.get("video_model") or "seedance"),
                    str(data.get("seconds_choice") or MODE.get("seconds") or "auto"),
                )
            except RuntimeError as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, result)
            return
        if path == "/api/scenes/seconds":
            try:
                index = int(data.get("index"))
                seconds = int(data.get("seconds"))
            except (TypeError, ValueError):
                self.send_json(400, {"error": "说第几场、几秒。"})
                return
            if index < 1 or index > len(SCENES):
                self.send_json(400, {"error": "没有这场。"})
                return
            if seconds < 4 or seconds > 30:
                self.send_json(400, {"error": "提交秒数只能是 4 到 30。"})
                return
            SCENES[index - 1]["seconds"] = seconds
            SCENES[index - 1]["needs_rewrite"] = True
            PROMPT_FROM["text"] = ""
            save_session()
            self.send_json(200, {"scenes": SCENES})
            return
        if path == "/api/stills":
            director_id = data.get("director_id") or ""
            if director_by_id(director_id) is None:
                self.send_json(400, {"error": "先选一位导演。"})
                return
            try:
                scene_no = int(data.get("scene_no") or 1)
            except (TypeError, ValueError):
                scene_no = 1
            try:
                stills = make_stills(
                    director_id,
                    str(data.get("place") or ""),
                    str(data.get("who") or ""),
                    str(data.get("remember") or ""),
                    str(data.get("ratio") or "16:9"),
                    scene_no,
                )
            except (FileNotFoundError, RuntimeError) as exc:
                self.send_json(502, {"error": str(exc)})
                return
            self.send_json(200, {"stills": stills})
            return
        if path == "/api/assets":
            name = str(data.get("name") or "")
            try:
                raw = base64.b64decode(data.get("data_base64") or "", validate=True)
                saved = store_asset(name, raw)
            except (ValueError, base64.binascii.Error):
                self.send_json(400, {"error": "这张图存不上"})
                return
            self.send_json(200, saved)
            return
        if path == "/api/assets/place":
            try:
                raw = base64.b64decode(data.get("data_base64") or "", validate=True)
                saved = place_asset(str(data.get("kind") or ""), str(data.get("name") or ""), raw)
            except (ValueError, base64.binascii.Error) as exc:
                self.send_json(400, {"error": str(exc) or "这件资产存不上"})
                return
            self.send_json(200, saved)
            return
        if path == "/api/assets/delete":
            try:
                saved = remove_asset(data.get("name") or "")
            except RuntimeError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, saved)
            return
        if path == "/api/comfy/submit":
            self.send_json(400,{"error":"请在分镜中确认提示词，并通过视频生成计划提交。"})
            return
        if path != "/api/run":
            self.send_json(404, {"error": "没有这个接口"})
            return
        director_id = data.get("director_id") or ""
        messages = data.get("messages") or []
        if director_by_id(director_id) is None:
            self.send_json(400, {"error": "先选一位导演"})
            return
        clean = usable_messages(messages)
        if not clean or clean[-1]["role"] != "user":
            self.send_json(400, {"error": "先写下这一场要做什么"})
            return
        try:
            begin_reply(director_id, clean)
        except RuntimeError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(200, {"thinking": True})



def reconcile_jobs():
    if TASK.get("state") != "idle":
        raise RuntimeError("先等待当前任务结束。")
    queue = comfy_queue()
    if not queue:
        raise RuntimeError("无法读取ComfyUI队列，不能确认是否已受理。")
    try:
        with urlopen(comfy_base() + "/history", timeout=15) as response:
            history = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取历史记录，不会自动重交。") from exc
    candidates = []
    for item in (queue.get("queue_running") or []) + (queue.get("queue_pending") or []):
        if isinstance(item, list) and len(item) > 2:
            candidates.append((str(item[1]), item[2]))
    for pid, entry in history.items():
        saved = entry.get("prompt") or []
        if len(saved) > 2:
            candidates.append((str(pid), saved[2]))
    recovered = 0
    for job in JOB.get("jobs") or []:
        if job.get("status") not in {"unknown", "submitting"}:
            continue
        matches = [pid for pid, graph in candidates if job.get("prefix") and job["prefix"] in json.dumps(graph, ensure_ascii=False)]
        if len(set(matches)) == 1:
            job.update({"prompt_id": matches[0], "status": "queued", "error": ""})
            for row in active().intelligence["ledger"]:
                if row["id"] == job.get("reservation_id"):
                    row["status"] = "accepted"
            recovered += 1
    save_session()
    return {"recovered": recovered, "jobs": JOB.get("jobs"), "unknown": sum(j.get("status") == "unknown" for j in JOB.get("jobs") or [])}


def already_up():
    try:
        with urlopen(f"http://{LOCAL}:{PORT}/api/health", timeout=1) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def resume_running():
    for row in read_index():
        pid = str(row.get("id") or "")
        if not re.fullmatch(r"[\w\-]+", pid):
            continue
        work = work_for(pid)
        if (work.job.get("phase") or "") == "running" and work.job.get("jobs"):
            ACTIVE.set(work)
            spawn(watch_episode)


def main():
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(CACHE_ROOT).free < 1024 * 1024 * 1024:
        print("提醒：缓存盘剩余不足1GB，请清理或配置cache_root。")
    ensure_projects()
    url = f"http://{LOCAL}:{PORT}"
    lan_urls = []
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith("127."):
                lan_urls.append(f"http://{ip}:{PORT}")
    except OSError:
        pass
    if already_up():
        print("本机访问：" + url)
        for item in lan_urls:
            print("同事访问：" + item)
        webbrowser.open(url)
        return
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    resume_running()
    print("本机访问：" + url)
    for item in lan_urls:
        print("同事访问：" + item)
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
