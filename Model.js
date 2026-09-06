// Shared pure logic for the omagovee plugin (no imports; used via .import).
// All colors come from qs.Commons tokens at the call site — nothing here
// produces hex literals.

function parseFirstLine(raw) {
  var line = String(raw || "").split("\n")[0].trim()
  if (line === "") return null
  try { return JSON.parse(line) } catch (e) { return null }
}

// Aggregate bar state from a helper `state` payload (devices rows).
// Only physical lights (kind rich or scenic) count; virtual group skipped.
// Returns: "on" | "off" | "mixed" | "offline" | "nokey" | "error" | "empty"
function aggregate(states, errorText, hasKey) {
  if (errorText) {
    if (!hasKey || errorText.indexOf("no_key") >= 0) return "nokey"
    if (errorText.indexOf("reach") >= 0 || errorText.indexOf("network") >= 0
        || errorText.indexOf("timed out") >= 0) return "offline"
    return "error"
  }
  if (!hasKey) return "nokey"
  if (!states || states.length === 0) return "checking"
  var counted = 0
  var on = 0
  for (var i = 0; i < states.length; i++) {
    var s = states[i]
    if (s.virtual) continue
    if (s.kind !== "rich" && s.kind !== "scenic") continue
    counted++
    if (s.online === false) continue
    if (s.props && s.props.powerSwitch === 1) on++
  }
  if (counted === 0) return "empty"
  if (on === counted) return "on"
  if (on === 0) return "off"
  return "mixed"
}

// alpha(color, a): Qt.rgba needs components; colors arrive as `color` values.
function withAlpha(c, a) {
  return Qt.rgba(c.r, c.g, c.b, a)
}

// blend(c1, c2, t): t=0 -> c1, t=1 -> c2. Component math only.
function blend(c1, c2, t) {
  return Qt.rgba(c1.r + (c2.r - c1.r) * t,
                 c1.g + (c2.g - c1.g) * t,
                 c1.b + (c2.b - c1.b) * t,
                 c1.a + (c2.a - c1.a) * t)
}

function colorFromRgbInt(v) {
  var n = Math.max(0, Math.min(0xFFFFFF, v | 0))
  return Qt.rgba(((n >> 16) & 0xFF) / 255, ((n >> 8) & 0xFF) / 255, (n & 0xFF) / 255, 1)
}

function rgbToHexInt(v) {
  return "#" + ("000000" + (v | 0).toString(16).toUpperCase()).slice(-6)
}

function clockTime(ts) {
  if (!ts) return ""
  var d = new Date(ts * 1000)
  function p(n) { return (n < 10 ? "0" : "") + n }
  return p(d.getHours()) + ":" + p(d.getMinutes())
}

// One-line tooltip for the bar glyph.
function tooltip(agg, states, updatedTs, hasKey, errorMessage) {
  var lines = []
  if (agg === "nokey") {
    lines.push("Govee Lights — setup needed")
    lines.push("Click to add your Govee API key")
    return lines.join("\n")
  }
  if (agg === "error") {
    lines.push("Govee Lights — error")
    lines.push(String(errorMessage || "check the panel for details"))
    return lines.join("\n")
  }
  var per = []
  var off = 0
  if (states) {
    for (var i = 0; i < states.length; i++) {
      var s = states[i]
      if (s.virtual) continue
      if (s.online === false) { off++; continue }
      var st = s.props && s.props.powerSwitch === 1 ? "on" : "off"
      per.push(s.name + ": " + st)
    }
  }
  if (per.length === 0) per.push("no lights")
  if (off > 0) per.push(String(off) + (off > 1 ? " offline" : " offline"))
  lines.push("Govee Lights — " + agg)
  lines.push(per.join(" · "))
  var t = clockTime(updatedTs)
  if (t) lines.push("updated " + t)
  return lines.join("\n")
}
