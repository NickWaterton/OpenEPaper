# OpenEPaper

A Python bridge between an [OpenEPaperLink](https://github.com/OpenEPaperLink/OpenEPaperLink) Access Point (BLE variant) and MQTT, with a live web UI for viewing and editing ESL (Electronic Shelf Label) tags.

Originally written to display Bambu Lab P1S 3D printer filament/AMS data on e-paper shelf tags, but general enough to drive any OpenEPaperLink tag via JSON templates.

---

## Features

- **MQTT integration** — subscribes to command topics so any home automation system (e.g. Home Assistant) can push template variable updates to tags
- **WebSocket-driven web UI** — live view of all tags; click any tag to edit its template variables; updates only the changed tag in the browser (no full-page refresh)
- **JSON template engine** — define tag layouts using the [OEPL JSON designer](https://atc1441.github.io/oepl_json_designer/); templates scale automatically to the actual tag resolution
- **Multi-colour support** — handles standard BWR (Black/White/Red) tags and Wolink BWRY (Black/White/Red/Yellow) tags
- **AP WebSocket listener** — receives real-time tag check-in events from the AP; auto-initialises new tags
- **Persistent tag database** — saves tag state to `open_epaper_link_tags.json` so it survives restarts

---

## Requirements

Python 3.12+ and the following packages:

```
aiomqtt
aiohttp
quart
quart-flask-patch
flask-bootstrap
hypercorn
requests-toolbelt
numpy
Pillow
```

Install with:
```bash
pip install aiomqtt aiohttp quart quart-flask-patch flask-bootstrap hypercorn requests-toolbelt numpy Pillow
```

---

## Usage

```
usage: OpenEPaper.py [-h] [-A AP] [-F FOLDER] [-s SERVER] [-p PORT]
                     [-l LOGIN] [-pw PASSWORD] [-t TOPIC] [-D]

OpenEPaper MQTT interface

options:
  -A, --ap        AP IP address (default: 192.168.1.164)
  -F, --folder    Folder for tag images used by web server (default: tag_images)
  -s, --server    MQTT broker address (default: 192.168.1.16)
  -p, --port      MQTT broker port (default: 1883)
  -l, --login     MQTT username (default: none)
  -pw,--password  MQTT password (default: none)
  -t, --topic     Base MQTT topic (default: /openepaper)
  -D, --debug     Enable debug logging
```

### Minimal example

```bash
python3 OpenEPaper.py -A 192.168.1.164 -s 192.168.1.10
```

The web UI is then available at `http://<host>:5000`.

---

## MQTT topics

| Topic | Direction | Description |
|---|---|---|
| `/openepaper/data/#` | Published | Tag status, vars, system info, logs |
| `/openepaper/command/<name>/vars` | Subscribe | Update template variables for a tag |
| `/openepaper/command/<name>/json` | Subscribe | Upload a raw JSON template to a tag |
| `/openepaper/command/<name>/upload` | Subscribe | Upload a JPEG image to a tag |
| `/openepaper/command/<name>/reboot` | Subscribe | Reboot the AP (`ON`) |
| `/openepaper/command/<name>/<var>` | Subscribe | Set a single variable directly |

`<name>` is the human-readable tag name (alias) as shown in the top-left of the tag display.

### Example — update an AMS tag from the command line

```bash
mosquitto_pub -h 192.168.1.10 \
  -t "/openepaper/command/AMS1/vars" \
  -m '{"pct": "75", "color": "red", "fil": "PLA", "type": "Bambu", "name": "AMS1"}'
```

---

## Web UI

Open `http://<host>:5000` in a browser.

- All known tags are displayed as card images (rendered from the raw tag bitmap)
- Click a tag to open an edit modal — change the template or any variable value
- Changes are sent via WebSocket and immediately uploaded to the AP
- A WebSocket status indicator (top-left) shows connection state

---

## Templates

Templates are defined in the `TEMPLATES` dict at the top of `OpenEPaper.py`. Each template is a list of OEPL JSON drawing commands plus a `vars` dict of default variable values and a `size` dict specifying the design resolution (the engine scales to the actual tag size automatically).

Built-in templates:

| Template | Description |
|---|---|
| `Empty` | Blank tag showing only the name |
| `AMS Tags` | AMS filament display with in-use highlight (BWR) |
| `AMS Tags 1` | Scaled-up AMS layout (BWR) |
| `AMS Tags 2` | AMS layout with Calibri fonts (BWR) |
| `Rack Tags` | Shelf/rack label with type line (BWR) |
| `Rack Tags BWRY` | Shelf/rack label with yellow band (BWRY) |

---

## Utility scripts

| Script | Description |
|---|---|
| `tag_types.py` | Tag hardware type database (fetched from AP or OpenEPaperLink repo) |

---

## AP requirements

- An [OpenEPaperLink](https://github.com/NickWaterton/OpenEPaperLink) AP with BLE support (the NickWaterton fork)
- Tags must be set to content mode **19 (JSON template)** for template-driven updates
- The AP must be reachable over HTTP and WebSocket from the machine running this script

---

## License

MIT
