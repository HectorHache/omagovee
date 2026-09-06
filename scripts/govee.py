#!/usr/bin/env python3
"""govee.py — Govee cloud API helper for the omagovee Omarchy plugin.

Design contract (v2 plan §2):
- Python 3 stdlib ONLY. Runs on macOS and Arch/Omarchy.
- stdout line 1 = pure JSON (QML/Model.js parses line 1 only).
- stdout line 2 = human gate marker ("CONTROL OK", "DOCTOR OK", ...) so
  GATES.md CHECK lines can grep it. Never parse line 2 in QML.
- The API key NEVER appears in output, logs, or error text. Device ids
  (MACs) are masked unless --verbose.
- Every state read / control / scenes call counts against a disk-backed
  per-device bucket (10 calls / 60 s, shared across short-lived spawns).
- Region fallback ladder on auth failure (community-reported eu/ap hosts);
  default host is verified-good for the author's account.
- set refuses to act without --confirm-physical (interactive user intent),
  except --echo-current (no-op echo: sends the CURRENT value back).

MIT License — Copyright (c) 2026 PythonMalone
"""
import argparse, json, os, re, sys, time, uuid
import urllib.request, urllib.error

# --------------------------------------------------------------------------
# paths & constants
# --------------------------------------------------------------------------
HOME = os.path.expanduser("~")
STATE_DIR = os.environ.get("GOVEE_STATE_DIR") or os.path.join(HOME, ".local", "state", "omagovee")
CACHE_DIR = os.environ.get("GOVEE_CACHE_DIR") or os.path.join(HOME, ".cache", "omagovee")
KEY_FILE = os.environ.get("GOVEE_KEY_FILE") or os.path.join(STATE_DIR, "govee.key")
FAV_FILE = os.path.join(STATE_DIR, "favorites.json")

API_BASE = os.environ.get("GOVEE_API_BASE", "https://openapi.api.govee.com")
FALLBACK_HOSTS = ["https://openapi-eu.api.govee.com", "https://openapi-ap.api.govee.com"]
RATE_MAX = 10          # calls per device per RATE_WINDOW (official limit)
RATE_WINDOW = 60.0     # seconds
LIST_TTL = 60.0        # device-list cache
STATE_TTL = 60.0       # per-device state cache
SCENES_TTL = 86400.0   # scenes are static-ish (24 h)

MAC_RE = re.compile(r"(?i)([0-9a-f]{2}(?::[0-9a-f]{2}){5,8})")


def _ensure_dirs():
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)


def jout(obj, marker=None):
    """Line 1: JSON. Optional line 2: human marker for GATES greps."""
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    if marker:
        print(marker)


def mask_text(s):
    return MAC_RE.sub(lambda m: m.group(1)[:8] + "\u2026" + m.group(1)[-5:], s)


def mask_id(dev_id):
    return dev_id[:8] + "\u2026" + dev_id[-5:]


def mask_obj(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("device", "id") and isinstance(v, str) and MAC_RE.match(v):
                out[k] = mask_id(v)
            else:
                out[k] = mask_obj(v)
        return out
    if isinstance(obj, list):
        return [mask_obj(x) for x in obj]
    if isinstance(obj, str):
        return mask_text(obj)
    return obj


# --------------------------------------------------------------------------
# key handling (never printed)
# --------------------------------------------------------------------------
def key_path():
    return KEY_FILE


def load_key():
    try:
        with open(key_path()) as f:
            k = f.read().strip()
    except OSError:
        return None
    return k or None


def save_key(k):
    _ensure_dirs()
    k = k.strip()
    if len(k) < 20 or len(k) > 80:
        raise ValueError("key looks malformed (length %d); refusing to store" % len(k))
    fd = os.open(key_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k)
    os.chmod(key_path(), 0o600)


# --------------------------------------------------------------------------
# http + envelope
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, code, message, retry_after=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


def http_request(url, body=None, key=None, timeout=10):
    """Returns parsed JSON. Raises ApiError on transport/app errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Govee-API-Key": key,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            retry_after = resp.headers.get("Retry-After")
    except urllib.error.HTTPError as e:
        retry_after = e.headers.get("Retry-After") if e.headers else None
        try:
            err = json.loads(e.read().decode() or "{}")
        except Exception:
            err = {}
        raise ApiError(err.get("code") or e.code,
                       err.get("message") or "HTTP %d" % e.code,
                       retry_after=retry_after)
    except urllib.error.URLError as e:
        raise ApiError("network", "cannot reach Govee API: %s" % getattr(e, "reason", e))
    try:
        parsed = json.loads(raw.decode())
    except Exception:
        raise ApiError("bad_response", "non-JSON response from API")
    if isinstance(parsed, dict) and parsed.get("code") not in (None, 200):
        raise ApiError(parsed.get("code"), parsed.get("message") or parsed.get("msg") or "api error",
                       retry_after=retry_after)
    return parsed


def api_get(url, key, bucket_id=None):
    _bucket_check(bucket_id)
    return http_request(url, key=key)


def api_post(url, body, key, bucket_id=None):
    _bucket_check(bucket_id)
    return http_request(url, body=body, key=key)


# --------------------------------------------------------------------------
# disk token bucket (shared across spawns; every spawn is a fresh process)
# --------------------------------------------------------------------------
def _bucket_file():
    return os.path.join(CACHE_DIR, "bucket.json")


def _bucket_check(device_id, now=None):
    """Fail fast if device_id already used its 10 calls this minute."""
    if not device_id:
        return
    now = now if now is not None else time.time()
    path = _bucket_file()
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
    ts_list = [t for t in data.get(device_id, []) if now - t < RATE_WINDOW]
    if len(ts_list) >= RATE_MAX:
        wait = int(RATE_WINDOW - (now - ts_list[0])) + 1
        raise ApiError("rate_limited",
                       "device rate limit: %d calls/%ds — retry in ~%ds" % (RATE_MAX, int(RATE_WINDOW), wait),
                       retry_after=wait)
    ts_list.append(now)
    data[device_id] = ts_list
    _atomic_write_json(path, data)


# --------------------------------------------------------------------------
# cache (60 s state, 24 h scenes) + flock single-flight on writes
# --------------------------------------------------------------------------
def _flock():
    try:
        import fcntl
        return fcntl
    except ImportError:
        return None


def _atomic_write_json(path, obj):
    _ensure_dirs()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _cache_read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _cache_get(path, ttl):
    data = _cache_read(path)
    if not data or time.time() - data.get("ts", 0) > ttl:
        return None
    return data


def _cache_write(path, obj):
    f = _flock()
    if f:
        try:
            lock_path = path + ".lock"
            with open(lock_path, "w") as lf:
                f.flock(lf, f.LOCK_EX)
                _atomic_write_json(path, obj)
                f.flock(lf, f.LOCK_UN)
            return
        except OSError:
            pass
    _atomic_write_json(path, obj)


# --------------------------------------------------------------------------
# API wrappers + device classification
# --------------------------------------------------------------------------
def api_devices(key, fresh=False):
    path = os.path.join(CACHE_DIR, "devices.json")
    if not fresh:
        cached = _cache_get(path, LIST_TTL)
        if cached:
            return cached["devices"]
    raw = api_get(API_BASE + "/router/api/v1/user/devices", key)
    devices = raw.get("data") or []
    if not isinstance(devices, list):
        raise ApiError("bad_response", "unexpected devices payload shape")
    _cache_write(path, {"ts": time.time(), "devices": devices})
    return devices


def classify(dev):
    """kind: rich (full controls) | simple (powerSwitch-only) | group | scenic."""
    sku = dev.get("sku") or ""
    if sku == "SameModeGroup":
        return "group"
    if sku == "DreamViewScenic":
        return "scenic"
    instances = {c.get("instance") for c in dev.get("capabilities", [])}
    if {"lightScene", "colorRgb", "brightness"} & instances:
        return "rich"
    return "simple"


def rich_devices(key):
    return [d for d in api_devices(key) if classify(d) == "rich"]


def api_state(key, sku, dev_id, fresh=False, bucket=True):
    path = os.path.join(CACHE_DIR, "state-%s.json" % dev_id)
    if not fresh:
        cached = _cache_get(path, STATE_TTL)
        if cached:
            return cached["props"], False
    body = {"requestId": str(uuid.uuid4()), "payload": {"sku": sku, "device": dev_id}}
    raw = api_post(API_BASE + "/router/api/v1/device/state", body, key,
                   bucket_id=dev_id if bucket else None)
    props = (raw.get("payload") or {}).get("capabilities") or []
    _cache_write(path, {"ts": time.time(), "props": props})
    return props, True


def api_control(key, sku, dev_id, cap_type, instance, value):
    body = {"requestId": str(uuid.uuid4()),
            "payload": {"sku": sku, "device": dev_id,
                        "capability": {"type": cap_type, "instance": instance, "value": value}}}
    return api_post(API_BASE + "/router/api/v1/device/control", body, key, bucket_id=dev_id)


def api_scenes(key, sku, dev_id, fresh=False):
    path = os.path.join(CACHE_DIR, "scenes-%s.json" % dev_id)
    if not fresh:
        cached = _cache_get(path, SCENES_TTL)
        if cached:
            return cached["scenes"]
    body = {"requestId": str(uuid.uuid4()), "payload": {"sku": sku, "device": dev_id}}
    raw = api_post(API_BASE + "/router/api/v1/device/scenes", body, key, bucket_id=dev_id)
    scenes = (raw.get("payload") or {}).get("scenes")
    if scenes is None and isinstance(raw.get("data"), dict):
        scenes = raw["data"].get("scenes")
    if scenes is None and isinstance(raw.get("data"), list):
        scenes = raw["data"]
    scenes = scenes or []
    _cache_write(path, {"ts": time.time(), "scenes": scenes})
    return scenes


def _scene_name(item):
    for k in ("name", "sceneName", "title"):
        if item.get(k):
            return str(item[k])
    return None


def _scene_id(item):
    for k in ("id", "sceneId"):
        if item.get(k) is not None:
            return item[k]
    return None


def resolve_scene(key, sku, dev_id, name):
    """Name -> (paramId, id) from this device's scene list. Case-insensitive."""
    for item in api_scenes(key, sku, dev_id):
        if (_scene_name(item) or "").lower() == name.lower():
            pid = item.get("paramId")
            sid = _scene_id(item)
            if pid is not None and sid is not None:
                return {"paramId": pid, "id": sid}
    return None


def props_to_dict(props):
    out = {}
    for p in props:
        inst = p.get("instance")
        if inst:
            out[inst] = p.get("state", {}).get("value") if isinstance(p.get("state"), dict) else p.get("value")
    return out


# --------------------------------------------------------------------------
# favorites (D3: scene NAMES, per-device resolution at apply time)
# --------------------------------------------------------------------------
def load_favorites():
    data = _cache_read(FAV_FILE)
    names = data.get("names", []) if isinstance(data, dict) else []
    return [n for n in names if isinstance(n, str)]


def save_favorites(names):
    _ensure_dirs()
    _atomic_write_json(FAV_FILE, {"names": names})


# --------------------------------------------------------------------------
# sku defaults (ranges are NOT exposed by the API — v2 §2/B3)
# --------------------------------------------------------------------------
def load_sku_defaults():
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "sku_defaults.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def range_for(sku, instance, kind):
    """(min,max) for a slider bound. Capability presence drives WHICH controls
    render; this table drives bounds; errors surface honestly, never silent."""
    table = load_sku_defaults()
    entry = table.get(sku) or table.get("_default", {})
    if instance == "brightness":
        return 1, 100
    if instance == "colorTemperatureK":
        r = entry.get("colorTemperatureK")
        return tuple(r) if r else (2000, 9000)
    return None


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------
def cmd_list(args, key):
    devices = api_devices(key)
    out = []
    for i, d in enumerate(devices):
        kind = classify(d)
        insts = sorted({c.get("instance") for c in d.get("capabilities", [])})
        out.append({"index": i, "id": mask_id(d.get("device", "")), "sku": d.get("sku"),
                    "name": d.get("deviceName"), "kind": kind,
                    "bounds": {inst: range_for(d.get("sku"), inst, kind)
                               for inst in ("brightness", "colorTemperatureK")
                               if inst in insts},
                    "controls": insts})
    jout({"ok": True, "devices": out, "count": len(out)})


def _fresh_device(key, index):
    devices = api_devices(key, fresh=True)
    if not (0 <= index < len(devices)):
        raise ApiError("no_such_device", "device index %d out of range (0..%d)" % (index, len(devices) - 1))
    return devices[index]


def _is_virtual(d):
    return classify(d) in ("group", "scenic")


def cmd_state(args, key):
    devices = api_devices(key)
    sel = [devices[args.device_index]] if args.device_index is not None else devices
    res = []
    for i, d in enumerate(devices):
        if d not in sel:
            continue
        if _is_virtual(d):
            # state endpoint does not know virtual device ids ("devices not
            # exist" verified live) — panel shows them as toggle-only
            res.append({"index": i, "id": mask_id(d.get("device", "")), "sku": d.get("sku"),
                        "name": d.get("deviceName"), "kind": classify(d), "virtual": True,
                        "online": None, "fresh": False, "props": {}})
            continue
        props, fresh = api_state(key, d.get("sku"), d.get("device"), fresh=args.fresh)
        p = props_to_dict(props)
        # current scene name enrichment when cache has it
        scene = p.get("lightScene")
        if isinstance(scene, dict) and not args.no_scene_names:
            try:
                for item in api_scenes(key, d.get("sku"), d.get("device")):
                    if _scene_id(item) == scene.get("id"):
                        p["lightSceneName"] = _scene_name(item)
                        break
            except ApiError:
                pass
        res.append({"index": i, "id": mask_id(d.get("device", "")), "sku": d.get("sku"),
                    "name": d.get("deviceName"), "kind": classify(d),
                    "online": bool(p.get("online")), "fresh": fresh,
                    "props": {k: v for k, v in p.items() if k != "online"}})
    jout({"ok": True, "devices": res})


def _set_one(key, d, instance, value):
    sku, dev_id = d.get("sku"), d.get("device")
    if instance == "powerSwitch":
        cap_type = "devices.capabilities.on_off"
        value = 1 if str(value).strip().lower() in ("1", "true", "on") else 0
    elif instance in ("brightness", "colorTemperatureK"):
        cap_type = "devices.capabilities.range"
        lo, hi = range_for(sku, instance, classify(d))
        value = max(lo, min(hi, int(str(value).strip())))
    elif instance == "colorRgb":
        cap_type = "devices.capabilities.color_setting"
        value = _parse_color(value)
    else:
        raise ApiError("unsupported_instance", "instance %r not supported by set" % instance)
    api_control(key, sku, dev_id, cap_type, instance, value)
    # B7: successful control invalidates this device's state cache so the
    # next read is fresh (optimistic UI never re-reads a stale value).
    stale = os.path.join(CACHE_DIR, "state-%s.json" % dev_id)
    if os.path.exists(stale):
        try:
            os.unlink(stale)
        except OSError:
            pass
    return value


def _parse_color(value):
    """Accept 0xRRGGBB, #RRGGBB, or plain int. Clamp to 0..0xFFFFFF."""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("#"):
            s = "0x" + s[1:]
        v = int(s, 16) if s.lower().startswith("0x") else int(s, 10)
    else:
        v = int(value)
    return max(0, min(0xFFFFFF, v))


def cmd_set(args, key):
    # Real physical changes require interactive user intent (QML always
    # passes --confirm-physical). --echo-current is the only exempt path
    # (no-op: sends the CURRENT value back, zero visible effect — G3b).
    if not args.confirm_physical and not args.echo_current:
        raise ApiError("refusing",
                       "set requires --confirm-physical (interactive user intent) "
                       "or --echo-current")
    if args.echo_current:
        d = _fresh_device(key, args.device_index)
        sku, dev_id = d.get("sku"), d.get("device")
        props, _ = api_state(key, sku, dev_id, fresh=True)
        p = props_to_dict(props)
        if args.instance not in p:
            raise ApiError("instance_absent", "instance %r has no current value on this device" % args.instance)
        sent = _set_one(key, d, args.instance, p[args.instance])
        jout({"ok": True, "op": "echo", "device": mask_id(dev_id), "sku": sku,
              "instance": args.instance, "echoed_value": sent},
             "CONTROL OK (echo; no visible change)")
        return
    if args.scene_name:
        d = _fresh_device(key, args.device_index)
        sku, dev_id = d.get("sku"), d.get("device")
        scene = resolve_scene(key, sku, dev_id, args.scene_name)
        if not scene:
            raise ApiError("scene_not_found",
                           "scene %r not found on this device (or scenes not cached)" % args.scene_name)
        api_control(key, sku, dev_id, "devices.capabilities.dynamic_scene", "lightScene", scene)
        jout({"ok": True, "op": "scene", "device": mask_id(dev_id), "sku": sku,
              "scene": args.scene_name, "applied": scene},
             "CONTROL OK (scene %s)" % args.scene_name)
        return
    if args.master:
        target = 1 if str(args.value).strip().lower() in ("1", "true", "on") else 0
        lamps = rich_devices(key)
        if not lamps:
            raise ApiError("no_lamps", "no rich lamps found for master fan-out")
        results = []
        for d in lamps:
            try:
                sent = _set_one(key, d, "powerSwitch", target)
                results.append({"device": mask_id(d.get("device", "")), "ok": True, "value": sent})
            except ApiError as e:
                results.append({"device": mask_id(d.get("device", "")), "ok": False,
                                "error": e.code, "message": e.message})
        ok = all(r["ok"] for r in results)
        jout({"ok": ok, "op": "master", "value": target, "per_device": results},
             "CONTROL OK (master fan-out, %d lamp%s)" % (len(results), "s" if len(results) != 1 else "") if ok
             else "CONTROL FAILED (master fan-out)")
        return
    if args.group:
        target = 1 if str(args.value).strip().lower() in ("1", "true", "on") else 0
        devices = api_devices(key)
        g = next((d for d in devices if classify(d) == "group"), None)
        if not g:
            jout({"ok": False, "op": "group", "skipped": True}, "SKIPPED (no group device)")
            return
        sent = _set_one(key, g, "powerSwitch", target)
        jout({"ok": True, "op": "group", "device": mask_id(g.get("device", "")), "value": sent},
             "CONTROL OK (group)")
        return
    if not args.confirm_physical:
        raise ApiError("refusing",
                       "set requires --confirm-physical (interactive user intent) "
                       "or --echo-current / --scene-name / --master / --group")
    d = _fresh_device(key, args.device_index)
    sent = _set_one(key, d, args.instance, args.value)
    jout({"ok": True, "op": "set", "device": mask_id(d.get("device", "")),
          "sku": d.get("sku"), "instance": args.instance, "value": sent},
         "CONTROL OK STATE %s=%s" % (args.instance, sent))


def cmd_scenes(args, key):
    devices = api_devices(key)
    d = devices[args.device_index] if args.device_index is not None else next(
        (x for x in devices if classify(x) == "rich"), None)
    if d is None:
        raise ApiError("no_device", "no scene-capable device found")
    items = api_scenes(key, d.get("sku"), d.get("device"), fresh=args.fresh)
    favs = set(load_favorites())
    out = []
    for item in items:
        name = _scene_name(item)
        if name is None:
            continue
        out.append({"name": name, "id": _scene_id(item), "paramId": item.get("paramId"),
                    "favorite": name in favs})
    out.sort(key=lambda s: (not s["favorite"], s["name"].lower()))
    jout({"ok": True, "device_index": devices.index(d), "device": mask_id(d.get("device", "")),
          "sku": d.get("sku"), "count": len(out), "scenes": out})


def cmd_favorites(args, key):
    _ = key  # favorites are pure local state
    names = load_favorites()
    if args.op == "list":
        jout({"ok": True, "names": names})
        return
    if not args.name:
        raise ApiError("bad_args", "favorites add/remove requires --name")
    if args.op == "add":
        if args.name not in names:
            names.append(args.name)
            save_favorites(names)
    elif args.op == "remove":
        if args.name not in names:
            jout({"ok": False, "error": "not_found", "name": args.name})
            return
        names.remove(args.name)
        save_favorites(names)
    jout({"ok": True, "op": args.op, "name": args.name, "names": names})


def _probe_host(key, base):
    """Returns (base, devices_count) or raises ApiError."""
    global API_BASE
    saved = API_BASE
    try:
        API_BASE = base
        devices = api_devices(key, fresh=True)
        return base, len(devices)
    finally:
        API_BASE = saved


def cmd_onboard(args, key):
    _ = key
    key = None
    if args.key_file:
        with open(args.key_file) as f:
            key = f.read().strip()
    elif os.environ.get("GOVEE_ONBOARD_KEY"):
        # QML channel (Quickshell Process.environment QVariantHash) — keeps
        # the key out of argv, logs and repos; env is process-private.
        key = os.environ["GOVEE_ONBOARD_KEY"].strip()
    elif not sys.stdin.isatty():
        key = sys.stdin.read().strip()
    if not key:
        raise ApiError("no_key",
                       "no key given: pipe it on stdin (non-tty) or pass --key-file")
    # validate: primary host, then region ladder on auth failure
    err = None
    for base in [API_BASE] + FALLBACK_HOSTS:
        try:
            _probe_host(key, base)
            save_key(key)
            jout({"ok": True, "host": base}, "ONBOARD OK (key stored, chmod 600)")
            return
        except ApiError as e:
            err = e
            if e.code not in ("network", 401, 403):
                break
            if e.code not in (401, 403) and base == API_BASE:
                break
    raise err or ApiError("no_key", "key rejected by all hosts")


def cmd_doctor(args, key):
    problems = []
    host_errors = []
    if not key:
        problems.append("no key: run 'onboard' (paste key on stdin) or place it at %s" % key_path())
    devs = None
    hosts_tried = [API_BASE]
    active_host = API_BASE
    if key:
        for base in [API_BASE] + FALLBACK_HOSTS:
            try:
                active_host = base
                devs = api_devices(key, fresh=True)
                break
            except ApiError as e:
                hosts_tried.append(base)
                host_errors.append("host %s: %s" % (base, e.message))
                if e.code not in (401, 403):
                    break
    if host_errors and not devs:
        problems.extend(host_errors)
    detail = []
    if devs:
        for i, d in enumerate(devs):
            kind = classify(d)
            sku = d.get("sku")
            insts = {c.get("instance") for c in d.get("capabilities", [])}
            b = {inst: range_for(sku, inst, kind) for inst in ("brightness", "colorTemperatureK")
                 if inst in insts}
            row = {"index": i, "id": mask_id(d.get("device", "")), "name": d.get("deviceName"),
                   "sku": sku, "kind": kind, "bounds": b}
            if _is_virtual(d):
                row["virtual"] = True
            else:
                try:
                    props, _ = api_state(key, sku, d.get("device"), fresh=False)
                    p = props_to_dict(props)
                    row["online"] = bool(p.get("online"))
                    row["powerSwitch"] = p.get("powerSwitch")
                except ApiError as e:
                    row["state_error"] = e.message
                    problems.append("state %s: %s" % (mask_id(d.get("device", "")), e.message))
            detail.append(row)
        ok = not problems and any(r.get("kind") == "rich" for r in detail)
    else:
        ok = False
    bucket = _cache_read(os.path.join(CACHE_DIR, "bucket.json")) or {}
    summary = {"host": active_host, "hosts_tried": hosts_tried,
               "host_errors": host_errors, "key_present": bool(key),
               "device_count": len(detail), "devices": detail,
               "bucket_usage": {mask_id(k): len([t for t in v if time.time() - t < RATE_WINDOW])
                                for k, v in bucket.items()},
               "favorites": load_favorites(), "problems": problems}
    jout({"ok": ok, "doctor": summary}, "DOCTOR OK" if ok else "DOCTOR PROBLEMS: %d" % len(problems))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(prog="govee.py", description="Govee cloud helper (omagovee)")
    p.add_argument("--verbose", action="store_true", help="do not mask device ids")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="device inventory with kinds/bounds")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("state", help="per-device state (cached 60s; --fresh bypasses)")
    sp.add_argument("--device-index", type=int, default=None)
    sp.add_argument("--fresh", action="store_true")
    sp.add_argument("--no-scene-names", action="store_true", dest="no_scene_names")
    sp.set_defaults(fn=cmd_state)

    sp = sub.add_parser("set", help="control (requires --confirm-physical unless echo/master/group/scene)")
    sp.add_argument("--device-index", type=int, default=0)
    sp.add_argument("--instance", default="powerSwitch")
    sp.add_argument("--value", type=str, default="1", help="int for powerSwitch/brightness/colorTemperatureK; #RRGGBB, 0xRRGGBB or int for colorRgb")
    sp.add_argument("--confirm-physical", action="store_true", help="interactive user intent")
    sp.add_argument("--echo-current", action="store_true", help="G3b: send current value back (no-op)")
    sp.add_argument("--scene-name", default=None)
    sp.add_argument("--master", action="store_true", help="fan-out powerSwitch to all rich lamps")
    sp.add_argument("--group", action="store_true", help="G7c: use the group device (optional)")
    sp.set_defaults(fn=cmd_set)

    sp = sub.add_parser("scenes", help="scene list for a device (cached 24h)")
    sp.add_argument("--device-index", type=int, default=None)
    sp.add_argument("--fresh", action="store_true")
    sp.set_defaults(fn=cmd_scenes)

    sp = sub.add_parser("favorites", help="manage favorites (scene NAMES)")
    sp.add_argument("op", choices=["list", "add", "remove"])
    sp.add_argument("--name", default=None)
    sp.set_defaults(fn=cmd_favorites)

    sp = sub.add_parser("onboard", help="validate a key (stdin or --key-file) and store it 0600")
    sp.add_argument("--key-file", default=None)
    sp.set_defaults(fn=cmd_onboard, key_hint=None)

    sp = sub.add_parser("doctor", help="health + diagnostics")
    sp.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    if getattr(args, "fn", None) is None:
        p.print_help()
        return 1
    key = load_key() if args.cmd != "onboard" else None
    # doctor always runs: its job is diagnosing a missing key too
    if args.cmd not in ("onboard", "doctor") and not key:
        jout({"ok": False, "error": "no_key",
              "message": "no API key at %s — run: govee.py onboard" % key_path()})
        return 1
    try:
        args.fn(args, key)
        return 0
    except ApiError as e:
        out = {"ok": False, "error": str(e.code), "message": mask_text(e.message)}
        if e.retry_after:
            out["retry_after"] = e.retry_after
        jout(out)
        return 1
    except Exception as e:  # QML-safe surface for anything unexpected
        jout({"ok": False, "error": "internal", "message": mask_text(str(e))})
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
