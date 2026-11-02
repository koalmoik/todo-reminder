#!/usr/bin/python3
"""Microsoft To Do for GNOME: sync, reminders and a task window.

Commands:
  todo.py login <client-id>      sign in to Microsoft once
  todo.py sync                   fetch tasks, send reminders (systemd timer)
  todo.py list                   show open tasks in the terminal
  todo.py app [--startup|--new]  open the window
"""
import json
import re
import subprocess
import sys
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from i18n import WEEKDAYS, _, format_day

CONFIG_DIR = Path.home() / ".config/todo-reminder"
CACHE_DIR = Path.home() / ".cache/todo-reminder"
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_FILE = CONFIG_DIR / "token.json"  # legacy; the token now lives in the GNOME keyring
CACHE_FILE = CACHE_DIR / "tasks.json"
STATE_FILE = CACHE_DIR / "notified.json"

AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "Tasks.ReadWrite offline_access"

STATUS_COLORS = {"overdue": "#e01b24", "today": "#ff7800", "soon": "#e5a50a",
                 "later": "#3584e4", "none": "#9a9996"}
LIST_COLORS = ["#3584e4", "#2ec27e", "#9141ac", "#e66100", "#c01c28", "#1c71d8",
               "#26a269", "#986a44"]


class AuthError(Exception):
    pass


# ---------- Files ----------

def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path, data):
    """Write atomically; folder and file readable by the current user only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_suffix(".tmp")
    tmp.touch(mode=0o600)
    tmp.chmod(0o600)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(path)


# ---------- GNOME keyring ----------

def _secret():
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret
    schema = Secret.Schema.new("io.github.peter.TodoReminder", Secret.SchemaFlags.NONE,
                               {"kind": Secret.SchemaAttributeType.STRING})
    return Secret, schema


def keyring_load():
    Secret, schema = _secret()
    try:
        raw = Secret.password_lookup_sync(schema, {"kind": "token"}, None)
    except Exception as e:
        raise AuthError(_("Keyring not available: {error}").format(error=e))
    if raw is None and TOKEN_FILE.exists():  # migrate the old token file once
        tok = load_json(TOKEN_FILE, None)
        if tok:
            keyring_store(tok)
        TOKEN_FILE.unlink()
        return tok
    return json.loads(raw) if raw else None


def keyring_store(tok):
    Secret, schema = _secret()
    Secret.password_store_sync(schema, {"kind": "token"}, Secret.COLLECTION_DEFAULT,
                               "Microsoft To Do (GNOME)", json.dumps(tok), None)


# ---------- Sign-in (device code flow) ----------

def client_id():
    cid = load_json(CONFIG_FILE, {}).get("client_id")
    if not cid:
        raise AuthError(_("No client ID – please run 'todo.py login <client-id>'."))
    return cid


def store_token(tok):
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    keyring_store(tok)


def login(cid):
    save_json(CONFIG_FILE, {**load_json(CONFIG_FILE, {}), "client_id": cid})
    r = requests.post(f"{AUTH}/devicecode", data={"client_id": cid, "scope": SCOPES}, timeout=30)
    if not r.ok:
        sys.exit(_("Error: {error}").format(error=r.json().get('error_description', r.text)))
    dc = r.json()
    print(dc["message"], flush=True)
    interval = dc.get("interval", 5)
    while True:
        time.sleep(interval)
        tok = requests.post(f"{AUTH}/token", timeout=30, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cid, "device_code": dc["device_code"]}).json()
        if "access_token" in tok:
            store_token(tok)
            print(_("Signed in."))
            return
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        sys.exit(_("Sign-in failed: {error}").format(error=tok.get('error_description', err)))


def access_token():
    tok = keyring_load()
    if not tok:
        raise AuthError(_("Not signed in – please run 'todo.py login <client-id>'."))
    if time.time() < tok["expires_at"]:
        return tok["access_token"]
    new = requests.post(f"{AUTH}/token", timeout=30, data={
        "grant_type": "refresh_token", "client_id": client_id(),
        "refresh_token": tok["refresh_token"], "scope": SCOPES}).json()
    if "access_token" not in new:
        raise AuthError(_("Sign-in expired – please sign in again ({error}).").format(error=new.get('error')))
    new.setdefault("refresh_token", tok["refresh_token"])
    store_token(new)
    return new["access_token"]


# ---------- Graph API ----------

def graph(method, path, **kw):
    url = path if path.startswith("http") else GRAPH + path
    for _ in range(3):
        r = requests.request(method, url, timeout=30,
                             headers={"Authorization": f"Bearer {access_token()}"}, **kw)
        if r.status_code != 429:
            break
        time.sleep(int(r.headers.get("Retry-After", 5)))
    r.raise_for_status()
    return r.json() if r.content else None


def get_all(path):
    items = []
    while path:
        page = graph("GET", path)
        items += page.get("value", [])
        path = page.get("@odata.nextLink")
    return items


def create_task(list_id, fields):
    graph("POST", f"/me/todo/lists/{list_id}/tasks",
          json={k: v for k, v in fields.items() if v is not None})


def update_task(list_id, task_id, fields):
    graph("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json=fields)


def complete_task(list_id, task_id):
    update_task(list_id, task_id, {"status": "completed"})


def delete_task(list_id, task_id):
    graph("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}")


def create_list(name):
    graph("POST", "/me/todo/lists", json={"displayName": name})


def rename_list(list_id, name):
    graph("PATCH", f"/me/todo/lists/{list_id}", json={"displayName": name})


def delete_list(list_id):
    graph("DELETE", f"/me/todo/lists/{list_id}")


# ---------- Date/time ----------

def parse_graph_dt(d):
    """Graph dateTimeTimeZone -> local, timezone-aware datetime."""
    if not d:
        return None
    dt = datetime.fromisoformat(d["dateTime"][:19])
    tz = d.get("timeZone") or "UTC"
    try:
        dt = dt.replace(tzinfo=timezone.utc if tz.upper() == "UTC" else ZoneInfo(tz))
    except Exception:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def due_to_graph(d):
    return {"dateTime": f"{d.isoformat()}T00:00:00", "timeZone": "UTC"}


def dt_to_graph(dt):
    return {"dateTime": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC"}


def due_status(due_iso, today=None):
    if not due_iso:
        return "none"
    today = today or date.today()
    due = date.fromisoformat(due_iso)
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due <= today + timedelta(days=2):
        return "soon"
    return "later"


def date_label(d, today=None):
    """date -> 'Today', 'Tomorrow' or a full date such as 'Fri 31 Oct 2026'."""
    delta = (d - (today or date.today())).days
    return {0: _("Today"), 1: _("Tomorrow")}.get(delta) or format_day(d)


def due_label(due_iso, today=None):
    if not due_iso:
        return ""
    today = today or date.today()
    due = date.fromisoformat(due_iso)
    delta = (due - today).days
    text = format_day(due, year=due.year != today.year)
    prefix = _("Overdue") if delta < 0 else {0: _("Today"), 1: _("Tomorrow")}.get(delta)
    return f"{prefix} · {text}" if prefix else text


# ---------- Recurrence ----------

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
REPEAT_KINDS = ["none", "daily", "workdays", "weekly", "monthly", "yearly"]
REPEAT_LABELS = [_(x) for x in ("Never", "Daily", "Weekdays (Mon–Fri)", "Weekly", "Monthly", "Yearly")]
REPEAT_UNITS = {"daily": (_("day"), _("days")), "weekly": (_("week"), _("weeks")),
                "monthly": (_("month"), _("months")), "yearly": (_("year"), _("years"))}


def recurrence_from_graph(rec):
    """Graph patternedRecurrence -> {'kind', 'interval', 'days'} (days: 0=Mon .. 6=Sun)."""
    if not rec:
        return None
    pat = rec.get("pattern") or {}
    kind = {"daily": "daily", "weekly": "weekly", "absoluteMonthly": "monthly",
            "relativeMonthly": "monthly", "absoluteYearly": "yearly",
            "relativeYearly": "yearly"}.get(pat.get("type"), "daily")
    days = sorted(DAY_NAMES.index(d) for d in pat.get("daysOfWeek") or [] if d in DAY_NAMES)
    interval = pat.get("interval") or 1
    if kind == "weekly" and days == [0, 1, 2, 3, 4] and interval == 1:
        kind = "workdays"
    return {"kind": kind, "interval": interval, "days": days}


def recurrence_to_graph(kind, interval, days, due):
    if kind == "none":
        return None
    if kind == "workdays":
        kind, interval, days = "weekly", 1, [0, 1, 2, 3, 4]
    pattern = {"type": {"monthly": "absoluteMonthly", "yearly": "absoluteYearly"}.get(kind, kind),
               "interval": interval, "firstDayOfWeek": "monday"}
    if kind == "weekly":
        pattern["daysOfWeek"] = [DAY_NAMES[d] for d in (days or [due.weekday()])]
    if kind in ("monthly", "yearly"):
        pattern["dayOfMonth"] = due.day
    if kind == "yearly":
        pattern["month"] = due.month
    return {"pattern": pattern, "range": {"type": "noEnd", "startDate": due.isoformat()}}


def recurrence_label(rec):
    if not rec:
        return ""
    kind, n = rec["kind"], rec["interval"]
    if kind == "workdays":
        return _("Mon–Fri")
    base = (_(kind) if n == 1
            else _("every {n} {unit}").format(n=n, unit=REPEAT_UNITS[kind][1]))
    if kind == "weekly" and rec["days"]:
        base += " " + ", ".join(WEEKDAYS[d] for d in rec["days"])
    return base


# ---------- Sync ----------

def normalize_hex(text):
    """'#abc', 'abc', '#aabbcc' or 'aabbcc' -> '#aabbcc'; anything else -> None."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", (text or "").strip())
    if not m:
        return None
    h = m.group(1).lower()
    return "#" + (h if len(h) == 6 else "".join(c * 2 for c in h))


def color_hex(value):
    """List color as '#rrggbb'; also accepts the older index into LIST_COLORS."""
    if isinstance(value, int):
        return LIST_COLORS[value % len(LIST_COLORS)]
    return normalize_hex(value) or LIST_COLORS[0]


def list_color(list_id):
    """The user's local choice from config.json, else a color derived from the ID."""
    chosen = load_json(CONFIG_FILE, {}).get("list_colors", {}).get(list_id)
    if chosen is not None:
        return color_hex(chosen)
    return LIST_COLORS[zlib.crc32(list_id.encode()) % len(LIST_COLORS)]


def set_list_color(list_id, color):
    color = color_hex(color)
    config = load_json(CONFIG_FILE, {})
    config.setdefault("list_colors", {})[list_id] = color
    save_json(CONFIG_FILE, config)
    cache = load_json(CACHE_FILE, None)
    if cache:
        for lst in cache.get("lists", []):
            if lst["id"] == list_id:
                lst["color"] = color
        save_json(CACHE_FILE, cache)


def _notes(task):
    body = task.get("body") or {}
    text = body.get("content") or ""
    if body.get("contentType") == "html":
        text = re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>|</p>", "\n", text)).strip()
    return text.strip()


def fetch():
    lists = get_all("/me/todo/lists")
    tasks = []
    for lst in lists:
        for t in get_all(f"/me/todo/lists/{lst['id']}/tasks"
                         "?$filter=status%20ne%20'completed'&$top=100"):
            due = parse_graph_dt(t.get("dueDateTime"))
            rem = parse_graph_dt(t.get("reminderDateTime")) if t.get("isReminderOn") else None
            tasks.append({
                "id": t["id"], "list_id": lst["id"], "list": lst["displayName"],
                "title": t.get("title", ""), "importance": t.get("importance", "normal"),
                "due": due.date().isoformat() if due else None,
                "reminder": rem.isoformat() if rem else None,
                "notes": _notes(t), "recurrence": recurrence_from_graph(t.get("recurrence")),
            })
    data = {
        "updated": datetime.now().astimezone().isoformat(),
        "lists": [{"id": l["id"], "name": l["displayName"], "color": list_color(l["id"]),
                   "shared": l.get("isShared", False),
                   "default": l.get("wellknownListName") == "defaultList"} for l in lists],
        "tasks": tasks,
    }
    save_json(CACHE_FILE, data)
    return data


def notify_reminders(data):
    state = load_json(STATE_FILE, {})
    now = datetime.now().astimezone()
    for t in data["tasks"]:
        if not t["reminder"] or state.get(t["id"]) == t["reminder"]:
            continue
        rem = datetime.fromisoformat(t["reminder"])
        if rem <= now:
            if now - rem < timedelta(hours=12):
                body = " · ".join(x for x in (due_label(t["due"]), t["list"]) if x)
                subprocess.run(["notify-send", "-u", "critical", "-a", "To Do",
                                "-i", "alarm-symbolic", f"⏰ {t['title']}", body])
            state[t["id"]] = t["reminder"]
    ids = {t["id"] for t in data["tasks"]}
    save_json(STATE_FILE, {k: v for k, v in state.items() if k in ids})


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "app"
    try:
        if cmd == "login":
            login(args[1] if len(args) > 1 else client_id())
            fetch()
        elif cmd == "sync":
            notify_reminders(fetch())
        elif cmd == "list":
            data = fetch()
            for t in sorted(data["tasks"], key=lambda t: (t["due"] or "9999", t["title"])):
                print(f"{due_label(t['due']) or '-':28} {t['title']}  [{t['list']}]")
        elif cmd == "app":
            import gui
            gui.main(startup="--startup" in args, new="--new" in args)
        else:
            print(__doc__)
    except AuthError as e:
        sys.exit(str(e))
    except requests.RequestException as e:
        sys.exit(_("Connection to Microsoft failed: {error}").format(error=e))


if __name__ == "__main__":
    main()
