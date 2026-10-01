# omagovee — Govee Lights

An Omarchy (Quickshell) bar widget for Govee smart lights. Control power, brightness, colour temperature, RGB colour and scenes from a panel in the bar, without reaching for the phone app.

Talks to the Govee cloud API directly. Your API key stays in your own config and is never committed.

## Install

Copy this folder into `~/.config/omarchy/plugins/`, enable the plugin by the id listed in `manifest.json`, then reload the shell.

## Layout

- `BarWidget.qml` is the bar face and menu trigger.
- `Panel.qml` is the control panel: power, brightness, colour temperature, RGB and scenes.
- `Helper.qml` runs the Govee API calls; `Model.js` holds parsing and formatting.
- `scripts/` holds the device helpers.

## License

MIT. See `LICENSE`.
