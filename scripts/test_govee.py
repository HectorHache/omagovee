#!/usr/bin/env python3
"""Offline unit tests for govee.py — mocked transport, NO key, NO network.

Gate G1: run from repo root with `python3 scripts/test_govee.py`
Expect final line: ALL HELPER TESTS PASSED
"""
import io, json, os, re, sys, tempfile, contextlib

# Isolate state/cache BEFORE importing the helper
_tmp = tempfile.mkdtemp(prefix="omagovee-test-")
os.environ["GOVEE_STATE_DIR"] = os.path.join(_tmp, "state")
os.environ["GOVEE_CACHE_DIR"] = os.path.join(_tmp, "cache")
os.environ.pop("GOVEE_KEY_FILE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import govee

KEY = "t" * 36  # fake key, 36 chars like a real one
MAC_RE = re.compile(r"(?i)[0-9a-f]{2}(?::[0-9a-f]{2}){5,8}")

FAKE_DEVICES = [
    {"sku": "H6076", "device": "GOVTEST01", "deviceName": "Lamp One",
     "type": "devices.types.light",
     "capabilities": [
         {"type": "devices.capabilities.on_off", "instance": "powerSwitch"},
         {"type": "devices.capabilities.range", "instance": "brightness"},
         {"type": "devices.capabilities.color_setting", "instance": "colorRgb"},
         {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK"},
         {"type": "devices.capabilities.dynamic_scene", "instance": "lightScene"}]},
    {"sku": "H6076", "device": "GOVTEST02", "deviceName": "Lamp Two",
     "type": "devices.types.light",
     "capabilities": [
         {"type": "devices.capabilities.on_off", "instance": "powerSwitch"},
         {"type": "devices.capabilities.range", "instance": "brightness"},
         {"type": "devices.capabilities.color_setting", "instance": "colorRgb"},
         {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK"},
         {"type": "devices.capabilities.dynamic_scene", "instance": "lightScene"}]},
    {"sku": "SameModeGroup", "device": "GOVTESTGRP", "deviceName": "Virtual Group",
     "type": None,
     "capabilities": [{"type": "devices.capabilities.on_off", "instance": "powerSwitch"}]},
    {"sku": "DreamViewScenic", "device": "GOVTESTFAIRY", "deviceName": "Fairy Lights",
     "type": None,
     "capabilities": [{"type": "devices.capabilities.on_off", "instance": "powerSwitch"}]},
]

FAKE_PROPS = [
    {"type": "devices.capabilities.online", "instance": "online", "state": {"value": True}},
    {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "state": {"value": 0}},
    {"type": "devices.capabilities.range", "instance": "brightness", "state": {"value": 49}},
    {"type": "devices.capabilities.color_setting", "instance": "colorRgb", "state": {"value": 16744448}},
    {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK", "state": {"value": 3000}},
    {"type": "devices.capabilities.dynamic_scene", "instance": "lightScene", "state": {"value": {"paramId": 7, "id": "s7"}}},
]

FAKE_SCENES = [
    {"name": "Sleep", "paramId": 1, "id": "s1"},
    {"name": "Movie", "paramId": 2, "id": "s2"},
    {"name": "Aurora", "paramId": 3, "id": "s3"},
    {"name": "Fireworks", "paramId": 4, "id": "s4"},
    {"name": "Sunrise", "paramId": 5, "id": "s5"},
]


class FakeNet:
    """Replaces govee.http_request: records calls, returns scripted payloads."""

    def __init__(self):
        self.calls = []  # (url, body)
        self.control_values = []  # (device_id, instance, value)

    def __call__(self, url, body=None, key=None, timeout=10):
        assert key and len(key) >= 20, "key must reach transport intact"
        self.calls.append((url, body))
        if url.endswith("/user/devices"):
            return {"code": 200, "message": "success", "data": FAKE_DEVICES}
        if url.endswith("/device/state"):
            dev = body["payload"]["device"]
            if dev in ("GOVTESTGRP", "GOVTESTFAIRY"):
                raise govee.ApiError(400, "devices not exist")
            return {"requestId": body["requestId"], "msg": "success", "code": 200,
                    "payload": {"sku": body["payload"]["sku"], "device": dev,
                                "capabilities": FAKE_PROPS}}
        if url.endswith("/device/scenes"):
            return {"requestId": body["requestId"], "msg": "success", "code": 200,
                    "payload": {"scenes": FAKE_SCENES}}
        if url.endswith("/device/control"):
            cap = body["payload"]["capability"]
            self.control_values.append((body["payload"]["device"], cap["instance"], cap["value"]))
            return {"requestId": body["requestId"], "msg": "success", "code": 200, "data": {}}
        raise govee.ApiError("bad_response", "unexpected url %s" % url)


def run(args, stdin_text=None):
    """Run main() capturing stdout. Returns (code, parsed_line1, marker_line)."""
    fake = net
    out = io.StringIO()
    old_stdin = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out):
            code = govee.main(args)
    finally:
        sys.stdin = old_stdin
    lines = out.getvalue().strip().split("\n")
    line1 = json.loads(lines[0]) if lines else None
    marker = lines[1] if len(lines) > 1 else None
    return code, line1, marker, fake


def reset():
    global net
    net = FakeNet()
    govee.http_request = net
    # clean caches so every test starts cold
    for d in (govee.STATE_DIR, govee.CACHE_DIR):
        import shutil
        if os.path.isdir(d):
            shutil.rmtree(d)
    os.makedirs(govee.STATE_DIR, exist_ok=True)
    os.makedirs(govee.CACHE_DIR, exist_ok=True)
    with open(os.path.join(govee.STATE_DIR, "govee.key"), "w") as f:
        f.write(KEY)
    os.chmod(os.path.join(govee.STATE_DIR, "govee.key"), 0o600)


reset()

PASS = []
def check(name, cond, extra=""):
    if not cond:
        raise AssertionError("FAILED: %s %s" % (name, extra))
    PASS.append(name)
    print("ok -", name)

# ------------------------------------------------- mask functions (synthetic MACs)
def test_mask_functions():
    m = "12:34:56:78:9A:BC:DE:F0"
    check("mask_id shortens", govee.mask_id(m) == "12:34:56\u2026DE:F0", govee.mask_id(m))
    out = govee.mask_text("device " + m + " end")
    check("mask_text masks MAC", m not in out and "\u2026" in out, out)
    d = govee.mask_obj({"device": m, "name": "x"})
    check("mask_obj masks device key", d["device"] == "12:34:56\u2026DE:F0" and m not in json.dumps(d), d["device"])

# ---------------------------------------------------------------- no key
def test_no_key():
    reset()
    os.unlink(govee.key_path())
    code, d, _, _ = run(["list"])
    check("no-key guard", code == 1 and d["ok"] is False and d["error"] == "no_key")

def test_doctor_no_key():
    reset()
    os.unlink(govee.key_path())
    code, d, marker, _ = run(["doctor"])
    check("doctor no-key problems", d["ok"] is False and len(d["doctor"]["problems"]) == 1
          and "no key" in d["doctor"]["problems"][0] and marker.startswith("DOCTOR PROBLEMS"))

# ---------------------------------------------------------------- inventory
def test_list_classification_and_masking():
    reset()
    code, d, _, _ = run(["list"])
    check("list ok", code == 0 and d["ok"] and d["count"] == 4)
    kinds = {x["name"]: x["kind"] for x in d["devices"]}
    check("classification rich", kinds["Lamp One"] == "rich")
    check("classification group", kinds["Virtual Group"] == "group")
    check("classification scenic", kinds["Fairy Lights"] == "scenic")
    blob = json.dumps(d)
    check("no raw ids in output", "GOVTEST01" not in blob and "GOVTEST02" not in blob, blob[:200])
    check("masked ids present", d["devices"][0]["id"] == "GOVTEST0\u2026EST01" or ("\u2026" in d["devices"][0]["id"] and "GOVTEST01" not in d["devices"][0]["id"]), d["devices"][0]["id"])
    bounds = {x["name"]: x["bounds"] for x in d["devices"]}
    check("h6076 colorTemp bounds", bounds["Lamp One"]["colorTemperatureK"] == [2700, 6500])

# ---------------------------------------------------------------- state + cache
def test_state_and_cache():
    reset()
    code, d, _, _ = run(["state", "--device-index", "0"])
    check("state ok", code == 0 and d["ok"] and d["devices"][0]["online"] is True
          and d["devices"][0]["props"]["brightness"] == 49)
    calls_after_first = len(net.calls)
    code, d2, _, _ = run(["state", "--device-index", "0"])
    check("state cached 60s", len(net.calls) == calls_after_first and d2["devices"][0]["fresh"] is False)
    code, d3, _, _ = run(["state", "--device-index", "0", "--fresh"])
    check("state fresh bypass", d3["devices"][0]["fresh"] is True)

# ---------------------------------------------------------------- bucket
def test_rate_bucket():
    reset()
    for i in range(10):
        run(["state", "--device-index", "0", "--fresh"])
    code, d, _, _ = run(["state", "--device-index", "0", "--fresh"])
    check("bucket 11th blocked", code == 1 and d["error"] == "rate_limited" and d["retry_after"] >= 1)

# ---------------------------------------------------------------- set safety
def test_set_refuses_without_confirm():
    reset()
    code, d, _, _ = run(["set", "--device-index", "0", "--instance", "powerSwitch", "--value", "1"])
    check("set refusal", code == 1 and d["error"] == "refusing")

def test_set_power():
    reset()
    code, d, marker, _ = run(["set", "--device-index", "0", "--confirm-physical"])
    check("set control ok", code == 0 and d["ok"] and d["op"] == "set" and d["value"] == 1)
    check("set marker", "CONTROL OK STATE powerSwitch=1" in marker)
    check("set cap payload", net.control_values[0] == ("GOVTEST01", "powerSwitch", 1))
    check("cache invalidated", not os.path.exists(os.path.join(govee.CACHE_DIR, "state-GOVTEST01.json")))

def test_set_color_temp_clamp():
    reset()
    code, d, _, _ = run(["set", "--device-index", "0", "--instance", "colorTemperatureK",
                         "--value", "9999", "--confirm-physical"])
    check("colorTemp clamp high", code == 0 and net.control_values[0][2] == 6500)
    reset()
    run(["set", "--device-index", "0", "--instance", "colorTemperatureK", "--value", "1", "--confirm-physical"])
    check("colorTemp clamp low", net.control_values[0][2] == 2700)

def test_set_color_rgb_hex():
    reset()
    code, d, _, _ = run(["set", "--device-index", "0", "--instance", "colorRgb",
                         "--value", "#ff8000", "--confirm-physical"])
    check("colorRgb hex parse", code == 0 and net.control_values[0][2] == 0xFF8000)
    check("colorRgb clamp", govee._parse_color("0xFFFFFFF") == 0xFFFFFF)

# ---------------------------------------------------------------- echo (G3b)
def test_echo_current():
    reset()
    code, d, marker, _ = run(["set", "--device-index", "0", "--instance", "powerSwitch", "--echo-current"])
    check("echo ok", code == 0 and d["ok"] and d["op"] == "echo" and d["echoed_value"] == 0)
    check("echo marker", "CONTROL OK (echo" in marker)
    check("echo sent current value", net.control_values[0][2] == 0)

# ---------------------------------------------------------------- master + group
def test_master_fanout():
    reset()
    code, d, marker, _ = run(["set", "--master", "--value", "0", "--confirm-physical"])
    check("master ok", code == 0 and d["ok"] and d["op"] == "master" and d["value"] == 0)
    check("master fan-out both lamps", len(net.control_values) == 2
          and all(v[1] == "powerSwitch" and v[2] == 0 for v in net.control_values))
    check("master marker", "CONTROL OK (master fan-out, 2 lamps)" in marker)

def test_group_skipped_and_used():
    reset()
    code, d, marker, _ = run(["set", "--group", "--value", "1", "--confirm-physical"])
    check("group used", code == 0 and d["op"] == "group" and net.control_values[0][0] == "GOVTESTGRP")
    check("group marker", "CONTROL OK (group)" in marker)

# ---------------------------------------------------------------- scenes + favorites
def test_scenes_and_favorites():
    reset()
    code, d, _, _ = run(["scenes", "--device-index", "0"])
    check("scenes ok", code == 0 and d["count"] == 5 and d["scenes"][0]["name"] == "Aurora"
          and [s["favorite"] for s in d["scenes"]] == [False] * 5)
    code, _, _, _ = run(["favorites", "add", "--name", "Aurora"])
    check("favorites add", code == 0)
    code, _, _, _ = run(["favorites", "add", "--name", "Movie"])
    code, d, _, _ = run(["scenes", "--device-index", "0"])
    check("scenes sorted fav first", [s["name"] for s in d["scenes"][:2]] == ["Aurora", "Movie"]
          and d["scenes"][0]["favorite"] is True)
    code, d, marker, _ = run(["set", "--device-index", "0", "--scene-name", "Aurora", "--confirm-physical"])
    check("scene apply", code == 0 and d["op"] == "scene" and d["applied"] == {"paramId": 3, "id": "s3"})
    code, _, _, _ = run(["favorites", "remove", "--name", "Aurora"])
    code, d, _, _ = run(["favorites", "list"])
    check("favorites persisted", d["names"] == ["Movie"])

# ---------------------------------------------------------------- onboard
def test_onboard_via_keyfile():
    reset()
    os.unlink(govee.key_path())
    kf = os.path.join(_tmp, "newkey.txt")
    with open(kf, "w") as f:
        f.write("k" * 36)
    code, d, marker, _ = run(["onboard", "--key-file", kf])
    check("onboard ok", code == 0 and d["ok"] and "ONBOARD OK" in marker)
    check("onboard key stored", open(govee.key_path()).read().strip() == "k" * 36)
    mode = oct(os.stat(govee.key_path()).st_mode & 0o777)
    check("onboard key 600", mode == "0o600", mode)

def test_onboard_via_env():
    reset()
    os.unlink(govee.key_path())
    os.environ["GOVEE_ONBOARD_KEY"] = "e" * 36
    try:
        code, d, marker, _ = run(["onboard"])
    finally:
        del os.environ["GOVEE_ONBOARD_KEY"]
    check("onboard env ok", code == 0 and d["ok"] and "ONBOARD OK" in marker)
    check("onboard env stored", open(govee.key_path()).read().strip() == "e" * 36)


# ---------------------------------------------------------------- doctor
def test_doctor_ok():
    reset()
    code, d, marker, _ = run(["doctor"])
    check("doctor ok", code == 0 and d["ok"] and d["doctor"]["key_present"]
          and d["doctor"]["device_count"] == 4 and marker == "DOCTOR OK")
    byname = {x["name"]: x for x in d["doctor"]["devices"]}
    check("doctor virtual flags", byname["Virtual Group"].get("virtual") is True
          and byname["Fairy Lights"].get("virtual") is True)
    check("doctor no state errors", all("state_error" not in x for x in d["doctor"]["devices"]))
    blob = json.dumps(d)
    check("doctor masks bucket ids", "GOVTEST01" not in blob)

# ---------------------------------------------------------------- error surface
def test_error_surface_no_traceback():
    reset()
    def failing(url, body=None, key=None, timeout=10):
        raise govee.ApiError("boom", "server said no")
    saved = govee.http_request
    govee.http_request = failing
    try:
        code, d, _, _ = run(["state", "--device-index", "0", "--fresh"])
    finally:
        govee.http_request = saved
    check("api error surfaced", code == 1 and d["ok"] is False and d["error"] == "boom"
          and d["message"] == "server said no")

def _run_all():
    for name in sorted(globals()):
        if name.startswith("test_"):
            print("# %s" % name)
            globals()[name]()

_run_all()
print("")
print("ALL HELPER TESTS PASSED (%d checks)" % len(PASS))
