# OpenEPaper

A Python bridge between an [OpenEPaperLink](https://github.com/OpenEPaperLink/OpenEPaperLink) Access Point (BLE variant) and MQTT, with a live web UI for viewing and editing ESL (Electronic Shelf Label) tags.

Originally written to display Bambu Lab P2S 3D printer filament/AMS data on e-paper shelf tags, but general enough to drive any OpenEPaperLink tag via JSON templates.

---

## Features

- **MQTT integration** — subscribes to command topics so any home automation system (e.g. Home Assistant) can push template variable updates to tags
- **WebSocket-driven web UI** — live view of all tags; click any tag to edit its template variables; updates only the changed tag in the browser (no full-page refresh)
- **Visual template designer** — built-in Fabric.js editor for creating and editing OEPL JSON templates; no external tools needed
- **JSON template engine** — templates scale automatically to the actual tag resolution; user templates saved to `user_templates.json`
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
  -A, --ap        AP IP address (default: 192.168.100.164)
  -F, --folder    Folder for tag images used by web server (default: tag_images)
  -s, --server    MQTT broker address (default: 192.168.100.16)
  -p, --port      MQTT broker port (default: 1883)
  -l, --login     MQTT username (default: none)
  -pw,--password  MQTT password (default: none)
  -t, --topic     Base MQTT topic (default: /openepaper)
  -D, --debug     Enable debug logging
```

### Minimal example

```bash
python3 OpenEPaper.py -A 192.168.100.164 -s 192.168.100.16
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
mosquitto_pub -h 192.168.100.16 \
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
- Click **Template Designer** to open the visual editor

---

## Template Designer

Open `http://<host>:5000/editor` or click the **Template Designer** button in the tag view.

### Overview

The designer is a full visual editor for OEPL JSON templates. Changes are reflected in the JSON panel in real time. Templates are saved server-side and immediately available to all tags.

Factory templates (marked ★) are read-only. All user-created templates are saved to `user_templates.json`.

### Toolbar

| Control | Description |
|---|---|
| Template selector | Choose which template to edit |
| **New** | Create a new template (starts as a copy of the current canvas) |
| **Save** | Save the current template |
| **Reset** | Discard unsaved changes and reload the last saved state |
| **Delete** | Delete the selected user template |
| Element buttons | Add a new element of that type to the canvas |
| Size / × / Apply | Set the design canvas size (width × height in pixels) |
| Rot | Tag display rotation (0°/90°/180°/270°) |
| ▲ / ▼ | Move the selected element forward/backward one layer |
| Delete | Remove the selected element |

### Element types

| Type | Description |
|---|---|
| **Text** | Single-line text. Supports variable substitution (`{varname}`), font, size, colour, alignment, optional background colour |
| **Box** | Filled rectangle with optional border (border is inset) |
| **RBox** | Rounded rectangle with corner radius and optional border |
| **Bars** | Progress bar made from repeated box segments. Driven by a numeric variable (0–100). Direction: left-to-right or right-to-left |
| **Line** | Single-pixel straight line between two points |
| **Triangle** | Filled triangle defined by three vertex points |
| **Circle** | Circle defined by centre point and radius, with optional border |
| **Image** | JPEG image stored on the AP filesystem. Pick a local file or an existing AP image; the editor previews it at the chosen size. On save the image is resized and uploaded to the AP automatically |
| **Textbox** | Multi-line text area with word wrap, line height, and alignment |

### Working with elements

- **Drag** to move; **corner handles** to resize
- Select an element to edit its properties in the **Element Properties** panel on the right
- For **line** and **triangle**, drag the blue endpoint handles directly on the canvas, or edit X/Y coordinates in the properties panel
- For **circle** and **text**, only uniform scaling is available (no stretching)
- The **Variable Defaults** panel lets you define template variables and set preview values used while designing

### Variables

Any text value in a template can reference a variable using `{varname}` syntax. Variables and their default values are defined in the `vars` entry of the template. When a tag checks in, the server substitutes live values (e.g. from MQTT) before uploading.

Add a variable with the **+ Add** button in the Variable Defaults panel. Delete it with the **×** button next to it.

### Images

1. Add an **Image** element to the canvas
2. In the Element Properties panel, click **Pick file…** to select a local JPEG/PNG, or choose an existing file from the **AP files** dropdown
3. The image loads as a live preview — drag and resize it on the canvas
4. Set the exact pixel dimensions in the **Width** / **Height** fields
5. **Save** the template — the server automatically:
   - Resizes the image to the specified pixel dimensions using PIL
   - Saves a local copy in `template_images/`
   - Uploads the resized image to the AP filesystem as `{template_name}_{index}.jpg`
   - Writes the AP filename into the saved template JSON

> **Note:** Image files on the AP are named `{template_name}_{index}.jpg` (e.g. `MyTemplate_0.jpg`). If you rename a template, re-save it to regenerate and re-upload the image files with the new name.

### JSON panel

The raw OEPL JSON is shown in the panel on the right and updates as you edit. You can also edit the JSON directly and click **Apply** to load it onto the canvas.

---

## Templates

Templates are stored in two places:

| File | Contents |
|---|---|
| `factory_templates.json` | Shipped read-only templates (marked ★ in the designer) |
| `user_templates.json` | Templates created or edited in the designer |

At startup both files are merged. Tags reference templates by name; the engine scales all coordinates to the actual tag resolution automatically.

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

## Tag hardware notes

### 2.13" display height (250×122 vs 250×128)

Several 2.13" tag types (confirmed: Gicisky BWR hw_type 177, Wolink BWRY hw_type 210) have a raw image buffer of 250×128 but a physical display of only 250×122 — the bottom 6 pixels of the buffer are never shown.

The tag database reports 128 as the height, which would cause template scaling to stretch content vertically by 6 pixels. To compensate, all 250-wide templates use a design height of **122**, and a Python-side override (`DISPLAY_SIZE_OVERRIDES` in `OpenEPaper.py`) maps any affected hw_type to its true display height for scaling purposes, while keeping the raw buffer size intact for image decoding.

If you add a new 2.13" tag type with the same quirk, add its hw_type to `DISPLAY_SIZE_OVERRIDES`:

```python
DISPLAY_SIZE_OVERRIDES = {
    177: {'height': 122},   # Gicisky BLE EPD BWR 2.13"
    # add new entries here
}
```

### Rotation

The `rotate` element in a template takes values 0–3, where:

| Value | Effect |
|---|---|
| 0 | Normal |
| 1 | 90° CW |
| 2 | 180° (upside down) |
| 3 | 90° CCW |

Rotation support is **tag hardware dependent**. Most 2.13" tags (Gicisky, Wolink) only support 0° and 180° — values 1 and 3 produce undefined results on these tags.

---

## AP requirements

- An [OpenEPaperLink](https://github.com/NickWaterton/OpenEPaperLink) AP with BLE support (the NickWaterton fork)
- Tags must be set to content mode **19 (JSON template)** for template-driven updates
- The AP must be reachable over HTTP and WebSocket from the machine running this script
- The AP must expose the SPIFFSEditor at `/edit` (standard in the firmware) for image upload support

---

## License

MIT
