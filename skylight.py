#!/usr/bin/env python3
"""
Skylight Calendar unofficial API client.

Reverse-engineered from the Skylight web app (app.ourskylight.com, an Expo /
React Native Web build). Talks to the same cloud API the physical Skylight
Calendar device uses, so anything you write here shows up on the device.

No third-party dependencies -- standard library only.

Auth: OAuth bearer token. This client can refresh expired access tokens.
Refreshed tokens are saved only when the active account and credentials came
from .env without environment overrides.

Config comes from environment or a .env file next to this script:
    SKYLIGHT_FRAME_ID       your frame/device id
    SKYLIGHT_ACCESS_TOKEN   short-lived bearer token
    SKYLIGHT_REFRESH_TOKEN  long-lived refresh token
    SKYLIGHT_TIMEZONE       default event timezone (UTC if unset)

Usage examples:
    ./skylight.py frames
    ./skylight.py categories
    ./skylight.py events --from 2026-09-01 --to 2026-09-30
    ./skylight.py add-event "Appointment" --start 2026-09-10T14:00 --end 2026-09-10T15:00 --who "Example person"
    ./skylight.py add-event "Trash day" --date 2026-09-12 --all-day
    ./skylight.py del-event <event_id>
    ./skylight.py lists
    ./skylight.py items <list_id>
    ./skylight.py add-item <list_id> "Buy milk"
    ./skylight.py check <list_id> <item_id>
    ./skylight.py del-item <list_id> <item_id>
    ./skylight.py chores --from 2026-09-01 --to 2026-09-08
"""
import json
import os
import sys
import tempfile
import urllib.request
import urllib.error
import urllib.parse

API_ROOT = "https://app.ourskylight.com/api"
OAUTH_URL = "https://app.ourskylight.com/oauth/token"
CLIENT_ID = "skylight-mobile"
USER_AGENT = "skylight-calendar-client/0.1 (unofficial educational client)"
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


# ---------------------------------------------------------------- config / .env
_ACCOUNT_KEYS = ("SKYLIGHT_FRAME_ID", "SKYLIGHT_ACCESS_TOKEN", "SKYLIGHT_REFRESH_TOKEN")


class _LoadedConfig(dict):
    """Keep file provenance out of user-facing configuration values."""


def load_env():
    cfg = _LoadedConfig()
    cfg._token_file = None
    cfg._file_identity = None
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    if (cfg.get("SKYLIGHT_ACCESS_TOKEN") and cfg.get("SKYLIGHT_REFRESH_TOKEN")
            and not any(os.environ.get(key) for key in _ACCOUNT_KEYS)):
        cfg._token_file = os.path.abspath(ENV_PATH)
        cfg._file_identity = tuple(cfg.get(key) for key in _ACCOUNT_KEYS)
    # environment overrides the file
    for k in _ACCOUNT_KEYS + ("SKYLIGHT_TIMEZONE",):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def save_tokens(access, refresh, path=None):
    """Atomically update an existing .env with owner-only permissions.

    Environment-only configuration never creates a credentials file.
    """
    path = ENV_PATH if path is None else path
    lines, seen = [], {"SKYLIGHT_ACCESS_TOKEN": False, "SKYLIGHT_REFRESH_TOKEN": False}
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return False
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key == "SKYLIGHT_ACCESS_TOKEN":
            out.append(f"SKYLIGHT_ACCESS_TOKEN={access}"); seen["SKYLIGHT_ACCESS_TOKEN"] = True
        elif key == "SKYLIGHT_REFRESH_TOKEN":
            out.append(f"SKYLIGHT_REFRESH_TOKEN={refresh}"); seen["SKYLIGHT_REFRESH_TOKEN"] = True
        else:
            out.append(line)
    if not seen["SKYLIGHT_ACCESS_TOKEN"]:
        out.append(f"SKYLIGHT_ACCESS_TOKEN={access}")
    if not seen["SKYLIGHT_REFRESH_TOKEN"]:
        out.append(f"SKYLIGHT_REFRESH_TOKEN={refresh}")
    fd, temporary_path = tempfile.mkstemp(prefix=".skylight-tokens-",
                                         dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("\n".join(out) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return True


# ------------------------------------------------------------------- the client
class Skylight:
    def __init__(self, cfg):
        self.frame = cfg.get("SKYLIGHT_FRAME_ID")
        self.access = cfg.get("SKYLIGHT_ACCESS_TOKEN")
        self.refresh = cfg.get("SKYLIGHT_REFRESH_TOKEN")
        self.timezone = cfg.get("SKYLIGHT_TIMEZONE") or "UTC"
        self._token_file = None
        if (isinstance(cfg, _LoadedConfig)
                and cfg._file_identity == tuple(cfg.get(key) for key in _ACCOUNT_KEYS)):
            self._token_file = cfg._token_file
        if not self.access:
            sys.exit("No SKYLIGHT_ACCESS_TOKEN configured (set it in .env).")

    # -- low level -----------------------------------------------------------
    def _raw(self, method, path, body=None, absolute=False):
        url = path if absolute else f"{API_ROOT}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.access}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            # Error bodies can contain private account data. Do not retain them.
            e.close()
            return e.code, None
        except urllib.error.URLError:
            sys.exit("Network request failed.")

    def _req(self, method, path, body=None):
        """Call the API, refreshing the token once on a 401."""
        status, payload = self._raw(method, path, body)
        if status == 401 and self.refresh:
            if self._do_refresh():
                status, payload = self._raw(method, path, body)
        if status >= 400:
            sys.exit(f"API request failed (HTTP {status}).")
        return payload

    def _do_refresh(self):
        body = {"grant_type": "refresh_token", "refresh_token": self.refresh,
                "client_id": CLIENT_ID}
        status, payload = self._raw("POST", OAUTH_URL, body, absolute=True)
        if status == 200 and isinstance(payload, dict) and payload.get("access_token"):
            self.access = payload["access_token"]
            self.refresh = payload.get("refresh_token", self.refresh)
            if self._token_file is not None:
                save_tokens(self.access, self.refresh, path=self._token_file)
            sys.stderr.write("[token refreshed]\n")
            return True
        return False

    def f(self, path):
        return f"frames/{self.frame}/{path}"

    # -- account -------------------------------------------------------------
    def frames(self):
        return self._req("GET", "frames")

    def categories(self):
        return self._req("GET", self.f("categories"))

    # -- calendar ------------------------------------------------------------
    def events(self, date_min, date_max):
        q = urllib.parse.urlencode({"date_min": date_min, "date_max": date_max})
        return self._req("GET", self.f(f"calendar_events?{q}"))

    def create_event(self, summary, starts_at=None, ends_at=None, all_day=False,
                     category_ids=None, description=None, location=None,
                     timezone_name=None, rrule=None):
        body = {
            "summary": summary,
            "kind": "standard",
            "category_ids": category_ids or [],
            "starts_at": starts_at,
            "ends_at": ends_at,
            "all_day": all_day,
            "rrule": [f"RRULE:{rrule}"] if rrule else None,
            "invited_emails": [],
            "location": location,
            "description": description,
            "timezone": timezone_name or self.timezone,
            "countdown_enabled": False,
        }
        return self._req("POST", self.f("calendar_events"), body)

    def update_event(self, event_id, **updates):
        return self._req("PUT", self.f(f"calendar_events/{event_id}"), updates)

    def delete_event(self, event_id, apply_to=None):
        # apply_to is a QUERY param (this|all|following) and only needed for
        # recurring events. Sending it as a body 500s the server.
        path = self.f(f"calendar_events/{event_id}")
        if apply_to:
            path += f"?apply_to={apply_to}"
        return self._req("DELETE", path)

    # -- lists ---------------------------------------------------------------
    def lists(self):
        return self._req("GET", self.f("lists"))

    def list_items(self, list_id):
        return self._req("GET", self.f(f"lists/{list_id}/list_items"))

    def add_item(self, list_id, label, category_id=None, section=None):
        body = {"label": label, "category_id": category_id, "section": section}
        return self._req("POST", self.f(f"lists/{list_id}/list_items"), body)

    def set_item_status(self, list_id, item_id, status):
        return self._req("PUT", self.f(f"lists/{list_id}/list_items/{item_id}"),
                         {"status": status})

    def delete_item(self, list_id, item_id):
        return self._req("DELETE", self.f(f"lists/{list_id}/list_items/{item_id}"))

    # -- chores --------------------------------------------------------------
    def chores(self, after, before):
        q = urllib.parse.urlencode({"after": after, "before": before})
        return self._req("GET", self.f(f"chores/all?{q}"))

    def create_chore(self, **fields):
        return self._req("POST", self.f("chores"), fields)

    def complete_chore(self, chore_id, **fields):
        return self._req("PUT", self.f(f"chores/{chore_id}/completions"), fields)


# ------------------------------------------------------------------------- CLI
def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def _rows(payload, cols):
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        _print(payload); return
    for it in data:
        a = it.get("attributes", {}) if isinstance(it, dict) else {}
        vals = [str(it.get("id", ""))] + [str(a.get(c, "")) for c in cols]
        print("  ".join(vals))


def main():
    import argparse
    p = argparse.ArgumentParser(description="Skylight Calendar API client")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("frames")
    sub.add_parser("categories")

    e = sub.add_parser("events")
    e.add_argument("--from", dest="dfrom", required=True)
    e.add_argument("--to", dest="dto", required=True)

    ae = sub.add_parser("add-event")
    ae.add_argument("summary")
    ae.add_argument("--start"); ae.add_argument("--end")
    ae.add_argument("--date", help="all-day date YYYY-MM-DD")
    ae.add_argument("--all-day", action="store_true")
    ae.add_argument("--who", action="append", default=[], help="category label(s)")
    ae.add_argument("--tz", help="override SKYLIGHT_TIMEZONE (default: UTC)")
    ae.add_argument("--location"); ae.add_argument("--desc")

    de = sub.add_parser("del-event"); de.add_argument("event_id")
    de.add_argument("--apply-to", choices=["this", "all", "following"],
                    help="for recurring events only")

    sub.add_parser("lists")
    it = sub.add_parser("items"); it.add_argument("list_id")
    ai = sub.add_parser("add-item"); ai.add_argument("list_id"); ai.add_argument("label")
    ck = sub.add_parser("check"); ck.add_argument("list_id"); ck.add_argument("item_id")
    uck = sub.add_parser("uncheck"); uck.add_argument("list_id"); uck.add_argument("item_id")
    di = sub.add_parser("del-item"); di.add_argument("list_id"); di.add_argument("item_id")

    ch = sub.add_parser("chores")
    ch.add_argument("--from", dest="dfrom", required=True)
    ch.add_argument("--to", dest="dto", required=True)

    args = p.parse_args()
    sky = Skylight(load_env())

    if args.cmd == "frames":
        _rows(sky.frames(), ["name", "timezone", "plus"])
    elif args.cmd == "categories":
        _rows(sky.categories(), ["label", "color", "linked_to_profile"])
    elif args.cmd == "events":
        _rows(sky.events(args.dfrom, args.dto), ["summary", "all_day", "starts_at"])
    elif args.cmd == "add-event":
        cat_ids = _labels_to_ids(sky, args.who)
        if args.date or args.all_day:
            day = args.date or args.start
            _print(sky.create_event(args.summary, starts_at=f"{day}T00:00:00",
                   ends_at=f"{day}T00:00:00", all_day=True, category_ids=cat_ids,
                   location=args.location, description=args.desc))
        else:
            _print(sky.create_event(args.summary, starts_at=args.start, ends_at=args.end,
                   all_day=False, category_ids=cat_ids, timezone_name=args.tz,
                   location=args.location, description=args.desc))
    elif args.cmd == "del-event":
        _print(sky.delete_event(args.event_id, apply_to=args.apply_to))
    elif args.cmd == "lists":
        _rows(sky.lists(), ["label", "kind", "color"])
    elif args.cmd == "items":
        _rows(sky.list_items(args.list_id), ["label", "status", "position"])
    elif args.cmd == "add-item":
        _print(sky.add_item(args.list_id, args.label))
    elif args.cmd == "check":
        _print(sky.set_item_status(args.list_id, args.item_id, "completed"))
    elif args.cmd == "uncheck":
        _print(sky.set_item_status(args.list_id, args.item_id, "pending"))
    elif args.cmd == "del-item":
        _print(sky.delete_item(args.list_id, args.item_id))
    elif args.cmd == "chores":
        _rows(sky.chores(args.dfrom, args.dto), ["name", "assignee_ids", "recurrence"])


def _labels_to_ids(sky, labels):
    if not labels:
        return []
    cats = sky.categories().get("data", [])
    categories = [(c["attributes"]["label"].casefold(), c["id"]) for c in cats]
    ids = []
    for want in labels:
        query = want.strip().casefold()
        exact = [cid for label, cid in categories if label == query]
        matches = exact or [cid for label, cid in categories if query and query in label]
        if not matches:
            sys.exit("No category matches --who; use categories to inspect available labels.")
        if len(matches) != 1:
            sys.exit("Ambiguous --who category; use a unique full label.")
        if matches[0] not in ids:
            ids.append(matches[0])
    return ids


if __name__ == "__main__":
    main()
