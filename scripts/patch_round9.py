import sys
p = "Panel.qml"
s = open(p).read()

def rep(old, new):
    global s
    assert old in s, "MISSING: " + old[:90]
    s = s.replace(old, new, 1)

# ---------------------------------------------------------------- 1. silent rate-limited READS
rep("""    onFailed: function (op, d) {
      root.states = []
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      root._confirmScheduled = false
      var msg = String(d && d.message ? d.message : "state refresh failed")
      if (d && d.error === "no_key") root.localNoKey = true
      if (hostWidget) { hostWidget.states = []; hostWidget.errorText = msg }
      root.say(msg, true)
    }""",
"""    onFailed: function (op, d) {
      // rate-limited reads are SILENT: keep the last states + desireds and let
      // the next poll retry — never wipe the UI or clear command truth on a
      // budget hiccup (reads share the per-device API budget with controls).
      if (d && d.error === "rate_limited") return
      root.states = []
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      root._confirmScheduled = false
      var msg = String(d && d.message ? d.message : "state refresh failed")
      if (d && d.error === "no_key") root.localNoKey = true
      if (hostWidget) { hostWidget.states = []; hostWidget.errorText = msg }
      root.say(msg, true)
    }""")

# ---------------------------------------------------------------- 2. heal 45 -> 90 s
rep("""    id: desiredHeal
    interval: 45000""",
"""    id: desiredHeal
    interval: 90000""")

# ---------------------------------------------------------------- 3. drop the 6.5 s confirm follow-up (polls cover it)
rep("""      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false
      // convergence follow-up: keep polling until every requested value lands
      if (root.anyPendingDesired() && !root._confirmScheduled) {
        root._confirmScheduled = true
        Qt.callLater(function () {
          root._confirmScheduled = false
          if (root.anyPendingDesired() && !root.noKey) root.refresh(true)
        }, 6500)
      }
    }""",
"""      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false
    }""")

# ---------------------------------------------------------------- 4. release rule: v wins unless it is the clobbered state
rep("""                  var eff = (briSlider._dragLast >= 0
                             && Math.abs(v - briSlider._dragLast) > 1)
                            ? briSlider._dragLast : v""",
"""                  // v (emitted liveValue) is truth UNLESS it equals the stale
                  // state resnap (PanelSlider clobbers liveValue before emit);
                  // only then fall back to the last drag position.
                  var eff = (v !== cur && Math.abs(v - cur) > 1) ? v
                          : ((briSlider._dragLast >= 0
                              && briSlider._dragLast !== cur
                              && Math.abs(briSlider._dragLast - cur) > 1)
                             ? briSlider._dragLast : v)""")
rep("""                  var eff = (tmpSlider._dragLast >= 0
                             && Math.abs(v - tmpSlider._dragLast) > 1)
                            ? tmpSlider._dragLast : v""",
"""                  var eff = (v !== cur && Math.abs(v - cur) > 1) ? v
                          : ((tmpSlider._dragLast >= 0
                              && tmpSlider._dragLast !== cur
                              && Math.abs(tmpSlider._dragLast - cur) > 1)
                             ? tmpSlider._dragLast : v)""")

# ---------------------------------------------------------------- 5. inline status next to master (no layout push)
rep("""            root.enqueue(["set", "--master", "--value",
                          target ? "1" : "0", "--confirm-physical"])
          }
        }
      }

      // status banner
      Text {
        width: parent.width
        text: root.statusText
        color: root.statusBad ? Color.urgent : Color.accent
        visible: root.statusText !== ""
        font.pixelSize: Style.font.body
        wrapMode: Text.Wrap
      }""",
"""            root.enqueue(["set", "--master", "--value",
                          target ? "1" : "0", "--confirm-physical"])
          }
        }
        Text {
          id: miniStatus
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(40, col.width - titleText.implicitWidth - masterSwitch.width
                              - Style.space(44))
          text: root.statusText
          color: root.statusBad ? Color.urgent : Color.accent
          visible: root.statusText !== ""
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
          horizontalAlignment: Text.AlignRight
        }
      }

""")
# delete the old banner block entirely
open(p, "w").write(s)
print("done; braces:", s.count("{"), s.count("}"))

p2 = "BarWidget.qml"
s2 = open(p2).read()
s2 = s2.replace("""    id: pollTimer
    interval: 25000
    running: root.panelOpen""",
"""    id: pollTimer
    interval: 30000
    running: root.panelOpen""")
open(p2, "w").write(s2)
print("BarWidget poll 30 s")
