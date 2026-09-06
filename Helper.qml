import QtQuick
import Quickshell.Io

// One-shot runner for scripts/govee.py. The helper owns the Govee API key,
// rate buckets and caches; QML never sees the key, only JSON.
//
// Contract (see scripts/govee.py docstring):
//   stdout line 1 = pure JSON  -> parsed and delivered via ok(op, data)
//   stdout line 2 = human gate marker (ignored here)
//   exit != 0 with no parseable JSON -> failed(op, { error, message })
//
// Use one instance per concurrent operation (panel + bar + per-action slots);
// each instance runs one process at a time and reports busy while running.
QtObject {
  id: root

  property string script: ""           // absolute path to scripts/govee.py
  property bool busy: proc.running
  property var environment: ({})       // extra env for this run (e.g. onboarding key)
  property bool useEnvironment: false  // pass root.environment to the child

  signal ok(string op, var data)
  signal failed(string op, var data)

  function run(op, args) {
    if (proc.running) return false
    var cmd = ["/usr/bin/python3", root.script]
    for (var i = 0; i < args.length; i++) cmd.push(args[i])
    proc.command = cmd
    if (root.useEnvironment) proc.environment = root.environment
    proc.running = true
    _op = op
    _parsed = false
    return true
  }

  property string _op: ""
  property bool _parsed: false

  function _deliver(raw) {
    var text = String(raw || "")
    var line = text.split("\n")[0].trim()
    if (line === "") return false
    var d = null
    try { d = JSON.parse(line) } catch (e) { return false }
    if (!d || typeof d !== "object") return false
    _parsed = true
    if (d.ok === true) root.ok(root._op, d)
    else root.failed(root._op, d)
    return true
  }

  Process {
    id: proc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root._deliver(text)
    }
    onExited: function (code) {
      // Python prints its JSON error line even on exit 1, so a parsed stdout
      // already delivered the verdict. Only act when nothing was parsed.
      if (!root._parsed) {
        root.failed(root._op, { ok: false, error: "exit", message: "helper exited (" + code + ")" })
      }
    }
  }
}
