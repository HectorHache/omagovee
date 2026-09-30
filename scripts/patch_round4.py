import re
p = "Panel.qml"
s = open(p).read()

def rep(old, new):
    global s
    assert old in s, "MISSING: " + old[:90]
    s = s.replace(old, new, 1)

# 1. desired-state props
rep("  property var _cardDesired: ({})      // \"index\" -> desired power bool",
    "  property var _cardDesired: ({})      // \"index\" -> desired power bool\n"
    "  property var _briDesired: ({})       // \"index\" -> desired brightness (held until API agrees)\n"
    "  property var _tmpDesired: ({})       // \"index\" -> desired colorTemperatureK")

# 2a. state ok: keep only unconverged desires
rep("""      root.masterOn = counted > 0 && on === counted
      root._masterHasDesired = false
      root._cardDesired = {}
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false""",
"""      root.masterOn = counted > 0 && on === counted
      root._masterHasDesired = false
      root._cardDesired = {}
      var bd = {}
      for (var bk in root._briDesired) {
        var br = root.rowForIndex(Number(bk))
        if (!(br && br.props) || br.props.brightness === undefined
            || br.props.brightness !== root._briDesired[bk]) bd[bk] = root._briDesired[bk]
      }
      root._briDesired = bd
      var td = {}
      for (var tk in root._tmpDesired) {
        var tr = root.rowForIndex(Number(tk))
        if (!(tr && tr.props) || tr.props.colorTemperatureK === undefined
            || Math.abs(tr.props.colorTemperatureK - root._tmpDesired[tk]) > 60) td[tk] = root._tmpDesired[tk]
      }
      root._tmpDesired = td
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false""")

# 2b. state failure: clear every desired
rep("""      root.states = []
      root._masterHasDesired = false
      root._cardDesired = {}""",
"""      root.states = []
      root._masterHasDesired = false
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}""")

# 2c. heal timer clears all desires
rep("""    onTriggered: {
      root._masterHasDesired = false
      root._cardDesired = {}
    }""",
"""    onTriggered: {
      root._masterHasDesired = false
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
    }""")

# 3. post-drain refresh delayed 2.5 s (API settle time)
rep("      Qt.callLater(function () { if (!root.busy) root.refresh() })",
    "      Qt.callLater(function () { if (!root.busy) root.refresh() }, 2500)")

# 4. rate-limit backoff 10 s
rep("""        root.say("Govee rate limit — retrying in a few seconds", false)
        root._queue.unshift(root._lastJob)
        Qt.callLater(function () { root._lastJobRequeued = false; root._drain() }, 5000)""",
"""        root.say("Govee rate limit — retrying in ~10 s", false)
        root._queue.unshift(root._lastJob)
        Qt.callLater(function () { root._lastJobRequeued = false; root._drain() }, 10000)""")

# 5. PADDING TRAP: inside the padded rich-controls column, every direct child
#    that binds width: parent.width overhangs by leftPadding+rightPadding.
start = s.index("leftPadding: Style.space(16)")
i = s.index("{", start)
depth = 0
j = i
while True:
    c = s[j]
    if c == "{": depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0: break
    j += 1
block = s[i:j+1]
fixed = re.sub(r"(\n(\s+))width: parent\.width(\n)",
               r"\1width: parent.width - parent.leftPadding - parent.rightPadding\3", block)
s = s[:i] + fixed + s[j+1:]
print("5 padding children fixed:", fixed.count("width: parent.width - parent.leftPadding - parent.rightPadding"))

# 6. brightness handler: hold desired until API confirms; binding prefers desired
rep("""                  if (cur >= 0 && want === cur) return     // no-op guard
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "brightness",""",
"""                  if (cur >= 0 && want === cur) return     // no-op guard
                  var idx = String(modelData.index)
                  var nd = {}
                  for (var k in root._briDesired) nd[k] = root._briDesired[k]
                  nd[idx] = want
                  root._briDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "brightness",""")
rep("""                  return (r && r.props && r.props.brightness !== undefined)
                         ? r.props.brightness : briSlider.value
                }
              }""",
"""                  var idx = String(modelData.index)
                  if (idx in root._briDesired) return root._briDesired[idx]
                  return (r && r.props && r.props.brightness !== undefined)
                         ? r.props.brightness : briSlider.value
                }
              }""")

# 7. colorTemp handler: hold desired; binding prefers desired over white-mode state
rep("""                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "colorTemperatureK",""",
"""                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  var idx = String(modelData.index)
                  var nd = {}
                  for (var k in root._tmpDesired) nd[k] = root._tmpDesired[k]
                  nd[idx] = want
                  root._tmpDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "colorTemperatureK",""")
rep("""                  var r = root.rowForIndex(modelData.index)
                  var k = (r && r.props) ? r.props.colorTemperatureK : 0
                  return (k > 0) ? k : tmpSlider.value
                }
              }""",
"""                  var idx = String(modelData.index)
                  if (idx in root._tmpDesired) return root._tmpDesired[idx]
                  var r = root.rowForIndex(modelData.index)
                  var k = (r && r.props) ? r.props.colorTemperatureK : 0
                  return (k > 0) ? k : tmpSlider.value
                }
              }""")

open(p, "w").write(s)
print("done, braces:", s.count("{"), s.count("}"))
