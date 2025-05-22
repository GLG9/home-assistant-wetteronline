# wetteronline

Home Assistant integration for data from **wetteronline.de**

> **⚠️ This project is currently not under active development.**
> Bug‑fix or maintenance pull requests are still welcome.

## Features

* Live observations plus hourly and daily forecasts from wetteronline.de
* Easy setup via **Config Flow** in the UI or traditional `configuration.yaml`.
* Compatible with HACS (add as Custom Repository) for hassle‑free updates.
* Fully typed code‑base and `manifest.json` with a `version` key (mandatory since Home Assistant 2023.6).

## Installation

1. Open **HACS** → *Integrations* → “⁝” → **Custom repositories**.
2. Add the URL of this repository and choose *Category* **Integration**.
3. Install the component and restart Home Assistant.
4. Go to *Settings* → **Devices & Services** and select **WetterOnline**.

*(Alternatively, copy the `custom_components/wetteronline` folder manually into your configuration directory and restart Home Assistant.)*

## Configuration

### UI (Config Flow)

Just enter the path part from wetteronline.de, e.g. `wetter/Berlin`.

## Known limitations

* WetterOnline does not provide an official public API; **DOM changes on the website can break the scraper**.
* Works only for locations available under the `wetter/<City>` path (Germany).
* No precipitation radar — you can embed the official radar as an iframe card instead.


## License

MIT — see `LICENSE`.
