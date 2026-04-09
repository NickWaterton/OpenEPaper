#!/usr/bin/env python3

"""
OpenEPapaer to MQTT server

This is intended for an MQTT interfact to an OpenEPaper AP
N Waterton 8/1/2026   V 1.0.0 : Initial Release
N Waterton 27/2/2026  V 1.0.1 : Added web page interface
N Waterton 9/4/2026   V 1.1.0 : Added Template Designer
"""

__version__ = '1.1.0'

import sys, json
import io, hashlib
import pprint
import logging
import argparse, os
import re
from pathlib import Path
from copy import deepcopy
from urllib import parse
from signal import SIGTERM, SIGINT
from datetime import datetime, timedelta
import asyncio
import aiohttp
from requests_toolbelt import MultipartEncoder
from collections import UserDict

import aiomqtt

#web page
import quart_flask_patch
from quart import Quart, render_template, make_response, current_app, websocket, request, redirect, url_for, jsonify
from flask_bootstrap import Bootstrap5
from hypercorn.config import Config
from hypercorn.asyncio import serve
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tag_types import get_tag_types_manager, get_hw_string

logging.basicConfig(level=logging.INFO)

DITHER_DISABLED = 0
DITHER_FLOYD_BURKES = 1
DITHER_ORDERED = 2
DITHER_DEFAULT = DITHER_ORDERED

MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds

STORAGE_VERSION = 1
#STORAGE_KEY = f"{DOMAIN}_tags"
RECONNECT_INTERVAL = 30

_HERE = Path(__file__).parent
FACTORY_TEMPLATES_FILE = _HERE / 'factory_templates.json'
USER_TEMPLATES_FILE    = _HERE / 'user_templates.json'
_log = logging.getLogger('Main')
SAVE_DELAY = 10
WEBSOCKET_TIMEOUT = 60
CONNECTION_TIMEOUT = 10
TAG_FILE = "open_epaper_link_tags.json"
TEMPLATE_IMAGES_DIR = _HERE / 'template_images'

# Some tags report a buffer size in the tag DB that is larger than the physical
# display (e.g. 250x128 buffer but only 250x122 visible pixels on 2.13" panels).
# Add hw_type entries here to override the height used for template scaling.
# Only height overrides are needed so far; add width if ever required.
DISPLAY_SIZE_OVERRIDES = {
    177: {'height': 122},   # Gicisky BLE EPD BWR 2.13" — buffer 128, display 122
}

'''
Color parameter
0 or "white": white
1 or "black": black
2 or "red": red
3 or "yellow": yellow (if the tag supports it)
4 or "lightgray" (uses pattern dither, not suitable for small fonts)
5 or "darkgray" (uses pattern dither, not suitable for small fonts)
6 or "pink" (uses pattern dither, not suitable for small fonts)
7 or "brown"
8 or "green"
9 or "blue"
10 or "orange"
"#rrggbb" for a custom color
'''

# name is a special placeholder, that automatically gets replaced by the tag name if assiged (default is mac)
# see https://atc1441.github.io/oepl_json_designer/
# to design templates

'''
Template AMS Tags  : AMS tags with in_use highlight (this is the default, and is currently in use)
         AMS Tags 1: AMS tags (simple version) scaled up
         AMS Tags 2: Same as 0 but with calibri fixed fonts
         Rack Tags : Racks tag
'''

TEMPLATES = {
"Empty"     :       [{ "text": [0, 0, "{name}", "Signika-SB.ttf", "black", 0, 15] },
                     { "vars": {"name": "Empty"}},
                     { "size": {"width": 250, "height": 122 }}
                   ],
 "AMS Tags" :       [{ "box" : [0, 0, 250, 70, "{in_use_col_bg}"]},
                     { "text": [0, 0, "{name}", "Signika-SB.ttf", "{fil_txt_col}", 0, 15] },
                     { "text": [250, 0, "{type}", "Signika-SB.ttf", "{fil_txt_col}", 2, 15] },
                     { "text": [125, 15, "{fil}", "Signika-SB.ttf", "{fil_txt_col}", 1, 50] },
                     { "rbox": [-10, 80, 90, 58, 10, "black"] },
                     { "rbox": [100, 80, 180, 58, 10, "red"] },
                     { "text": [5, 90, "{color}", "Signika-SB.ttf", "white", 0, 20] },
                     { "text": [245, 90, "{pct}%", "Signika-SB.ttf", "white", 2, 20] },
                     { "bars": [115, 90, 80, 20, "white", "{pct}"] },
                     { "vars": {"pct": "100", "color": "white", "fil": "PLA", "type": "?", "name": "AMS", "in_use_col_bg" : "white", "fil_txt_col": "black"}},
                     { "size": {"width": 250, "height": 122 }}
                   ],
 "AMS Tags 1" :    [{ "text": [250, 10, "{fil}", "fonts/calibrib100", "black", 1, 100] },
                    { "rbox": [-20, 160, 180, 116, 20, "black"] },
                    { "rbox": [200, 160, 360, 116, 20, "red"] },
                    { "text": [10, 180, "{color}", "fonts/calibrib40", "white", 0, 40] },
                    { "text": [490, 180, "{pct}%", "fonts/calibrib40", "white", 2, 40] },
                    { "bars": [230, 180, 160, 40, "white", "{pct}"] },
                    { "vars": {"pct": "100", "color": "white", "fil": "PLA" }},
                    { "size": {"width": 500, "height": 244 }}
                   ],
 "AMS Tags 2" :    [{ "box" : [0, 0, 250, 70, "{in_use_col_bg}"]},
                    { "text": [0, 0, "{name}", "fonts/calibrib15", "{fil_txt_col}", 0, 15] },
                    { "text": [250, 0, "{type}", "fonts/calibrib15", "{fil_txt_col}", 2, 15] },
                    { "text": [125, 25, "{fil}", "fonts/calibrib50", "{fil_txt_col}", 1, 50] },
                    { "rbox": [-10, 80, 90, 58, 10, "black"] },
                    { "rbox": [100, 80, 180, 58, 10, "red"] },
                    { "text": [5, 90, "{color}", "fonts/calibrib20", "white", 0, 20] },
                    { "text": [245, 90, "{pct}%", "fonts/calibrib20", "white", 2, 20] },
                    { "bars": [115, 90, 80, 20, "white", "{pct}"] },
                    { "vars": {"pct": "100", "color": "white", "fil": "PLA", "type": "?", "name": "AMS", "in_use_col_bg" : "white", "fil_txt_col": "black"}},
                    { "size": {"width": 250, "height": 122 }}
                   ],
 "Rack Tags" :     [{ "text": [0,0,"{name}","fonts/Signika-SB.ttf","black",0,15]},
                    { "text": [125,15,"{txt}","fonts/Signika-SB.ttf","black",1,50]},
                    { "box" : [0,80,250,58,"red"]},
                    { "text": [250,90,"{type}","fonts/Signika-SB.ttf","white",2,20]},
                    { "vars": {"name": "Rack", "txt" : "Open Racks", "type": "Sindoh PLA"}},
                    { "size": {"width": 250, "height": 122 }}
                   ],
"Rack Tags BWRY" : [{ "text": [0,0,"{name}","fonts/Signika-SB.ttf","black",0,15]},
                    { "text": [125,15,"{txt}","fonts/Signika-SB.ttf","black",1,47]},
                    { "box" : [0,80,250,58,"yellow"]},
                    { "text": [250,90,"{type}","fonts/Signika-SB.ttf","black",2,20]},
                    { "vars": {"name": "Rack", "txt" : "Open Racks", "type": "Sindoh PLA"}},
                    { "size": {"width": 250, "height": 122 }}
                   ]
}


def parseargs():
    # Add command line argument parsing
    parser = argparse.ArgumentParser(description='OpenEPaper MQTT interface Version: {}'.format(__version__))
    parser.add_argument('-A','--ap', action="store", type=str, default='192.168.100.164', help='AP ip address (default: %(default)s))')
    parser.add_argument('-F','--folder', action="store", type=str, default='tag_images', help='folder for web server to store tag images (default: %(default)s))')
    parser.add_argument('-s','--server', action="store", type=str, default="192.168.100.16", help='MQTT Server address (default: %(default)s))')
    parser.add_argument('-p','--port', action="store", type=int, default=1883, help='MQTT server port (default: %(default)s))')
    parser.add_argument('-l','--login', action="store", type=str, default="", help='optional MQTT server login (default: %(default)s))')
    parser.add_argument('-pw','--password', action="store", type=str, default="", help='optional MQTT server password (default: %(default)s))')
    parser.add_argument('-t','--topic', action="store", type=str, default="/openepaper", help='topic to publish OpenEPaper AP data to (default: %(default)s))')
    parser.add_argument('-D','--debug', action='store_true', default=False, help='Debug mode (default: %(default)s))')
    return parser.parse_args()

def validate_templates():
    '''
    ensure template name is correct in TEMPLATES
    '''
    for name, template in TEMPLATES.items():
        try:
            template_name = get_value_from_template('template', template)
            if not template_name:
                template.append({'template': name})
                log.warning(f'Added template:{name} to template {TEMPLATES[name]}')
            elif template_name != name:
                template[-1]['template'] = name
                log.warning(f'Updated template:{name} to template {TEMPLATES[name]} from {template_name}')
        except Exception as e:
            log.error(f'error updating TEMPLATE {name}: {e}')
  
def get_value_from_template(key, template, default=None):
    '''
    return the value of the first key item from a template, or default if not found
    could be a single value (like 'template'), or a dictionary like 'vars'
    '''
    return next((item[key] for item in template if key in item), default)

def load_all_templates():
    '''
    Load factory templates from factory_templates.json (falls back to hardcoded TEMPLATES),
    then overlay user templates from user_templates.json.
    Returns (factory_dict, user_dict).
    '''
    factory = {}
    if FACTORY_TEMPLATES_FILE.exists():
        try:
            with open(FACTORY_TEMPLATES_FILE) as f:
                factory = json.load(f)
        except Exception as e:
            _log.error(f'Error loading {FACTORY_TEMPLATES_FILE}: {e}')
    if not factory:
        factory = {k: list(v) for k, v in TEMPLATES.items()}

    user = {}
    if USER_TEMPLATES_FILE.exists():
        try:
            with open(USER_TEMPLATES_FILE) as f:
                user = json.load(f)
        except Exception as e:
            _log.error(f'Error loading {USER_TEMPLATES_FILE}: {e}')

    return factory, user

def save_user_templates(user_dict):
    try:
        with open(USER_TEMPLATES_FILE, 'w') as f:
            json.dump(user_dict, f, indent=2)
    except Exception as e:
        _log.error(f'Error saving {USER_TEMPLATES_FILE}: {e}')
    

        
    
class WEB:
    
    def __init__(self, folder=None, host=None, callback=None):
        self.log = logging.getLogger('Main.'+__class__.__name__)
        self.debug = self.log.getEffectiveLevel() <= logging.DEBUG
        self.web_host = '0.0.0.0'       #allow connection from any computer
        self.web_port = 5000
        self.ap_ip = host           # AP web page ip
        self.callback = callback
        self.tag_vars = {}
        self.version = {}
        self._update_event = asyncio.Event()
        self._changed_macs = set()
        self._removed_macs = set()
        self.connected = set()
        self._exit = False
        self.factory_templates, self.user_templates = load_all_templates()
        TEMPLATES.update(self.factory_templates)
        TEMPLATES.update(self.user_templates)
        validate_templates()
        self.templates = TEMPLATES
        if folder and folder.is_dir():
            self.app = Quart(__name__, static_folder=folder)
            self.bootstrap = Bootstrap5(self.app)
            self.app.config['BOOTSTRAP_BOOTSWATCH_THEME'] = 'cyborg'
            self.app.add_url_rule('/', 'show_tags', self.show_tags)
            self.app.add_url_rule('/editor', 'show_editor', self.show_editor)
            self.app.add_url_rule('/api/templates', 'api_templates', self.api_templates, methods=['GET'])
            self.app.add_url_rule('/api/templates/<path:name>', 'api_template', self.api_template, methods=['POST', 'DELETE'])
            self.app.add_url_rule('/api/images/stage', 'api_images_stage', self.api_images_stage, methods=['POST'])
            self.app.add_url_rule('/api/images/src/<path:src_id>', 'api_images_src', self.api_images_src, methods=['GET'])
            self.app.add_url_rule('/api/images/ap_list', 'api_images_ap_list', self.api_images_ap_list, methods=['GET'])
            self.app.add_url_rule('/api/images/ap_proxy/<path:filename>', 'api_images_ap_proxy', self.api_images_ap_proxy, methods=['GET'])
            self.app.add_websocket('/ws', 'ws', self.ws)
        else:
            self.app = None
            
    def close(self):
        '''
        exit server
        '''
        self.log.info('SIGINT/SIGTERM received, exiting')
        self._exit=True
        
    async def send_full_sync(self, ws_obj=None):
        '''
        send the complete tag-container HTML to one specific websocket (on connect)
        or to all connected websockets when ws_obj is None.
        '''
        try:
            targets = [ws_obj] if ws_obj else list(self.connected)
            if targets:
                tag_data = self.get_data()
                html = await render_template("tags.html", names=tag_data)
                data = {'type': 'sync_state', 'data': {'html': html}}
                for ws in targets:
                    await self.ws_send(data, ws)
        except Exception as e:
            self.log.exception(e)

    def get_tag_data(self, mac):
        '''
        return display data for a single tag (same shape as one entry from get_data)
        '''
        values = self.tag_vars.get(mac)
        if not values:
            return None
        v = self.get_version(mac)
        return {
            'vars': values['vars'].copy(),
            'version': v,
            'valid_templates': self.get_valid_templates(mac),
            'template': values['template'],
        }

    async def broadcast_changed_tags(self, changed_macs, removed_macs):
        '''
        send targeted per-tag updates; avoids replacing the whole container.
        removed tags get a remove_tag message so the browser can drop them.
        Uses an explicit app context because this runs in a standalone background task.
        '''
        try:
            for mac in removed_macs:
                await self.broadcast_updates({'mac': mac}, type='remove_tag')
            async with self.app.test_request_context('/'):
                for mac in changed_macs:
                    tag_data = self.get_tag_data(mac)
                    if tag_data:
                        html = await render_template(
                            "tag.html", mac=mac, values=tag_data,
                            templates=tag_data['valid_templates']
                        )
                        await self.broadcast_updates({'mac': mac, 'html': html}, type='update_tag')
        except Exception as e:
            self.log.exception(e)
        
    async def update_vars(self, mac, data):
        tag_vars = self.tag_vars.copy()
        self.tag_vars[mac] = data
        if tag_vars != self.tag_vars or self.get_version(mac) != self.version.get(mac):
            self._changed_macs.add(mac)
            self._update_event.set()
            self.log.info(f'updated {mac} with vars: {data}')
        
    async def remove_vars(self, mac):
        if self.tag_vars.pop(mac, None):
            file_path = self.get_file_path(mac)
            self.log.info('removing tag: {file_path}')
            file_path.unlink()
            self._removed_macs.add(mac)
            self._update_event.set()
        
    async def serve_forever(self, production=False):
        '''
        start everything up in either development or production environment
        '''
        if not self.app:
            self.log.warning('No folder defined - web app not starting')
            return
        if production:
            self.log.info('PRODUCTION Mode')
            config = Config()
            config.bind = '{}:{}'.format(self.web_host, self.web_port)
            config.loglevel = 'DEBUG' if self.debug else 'INFO'
            server = serve(self.app, config, shutdown_trigger=self.shutdown_trigger)
        else:
            self.log.info('DEVELOPMENT Mode')
            server = self.app.run_task(host=self.web_host, port=self.web_port, debug=self.debug,  shutdown_trigger=self.shutdown_trigger)
        self.log.info('Serving files from: {} on host: {}: port {}'.format(self.app.static_folder, self.web_host, self.web_port))
        try:
            await asyncio.gather(server, self.start_monitoring(), return_exceptions=False)
        except asyncio.CancelledError:
            self.log.info('Cancelled')
        
    async def shutdown_trigger(self):
        '''
        just loop until self._exit is set
        This should trigger the server shutdown on exit
        '''
        while not self._exit:
            await asyncio.sleep(1)
        self.log.info('shutdown initiated')
        
    def get_version(self, mac):
        img_path = self.get_file_path(mac)
        return int(img_path.stat().st_mtime) if img_path.exists() else 0
        
    def get_file_path(self, mac):
        return Path(self.app.static_folder) / f'{mac}.jpg'
        
    async def start_monitoring(self):
        '''
        runs the global websocket sender as the background monitoring task
        '''
        await self.sending()
        self.log.warning('exited')
        
    async def sending(self):
        '''
        single global task: send per-tag updates and pings to all connected websockets.
        wakes immediately on _update_event; otherwise fires a ping every ~10 s.
        '''
        self.log.info('websocket sender started')
        ping_count = 0
        while not self._exit:
            try:
                await asyncio.wait_for(self._update_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            ping_count += 1
            if ping_count >= 10:
                ping_count = 0
                await self.broadcast_updates({}, type='ping')
            if self._update_event.is_set():
                self._update_event.clear()
                changed = self._changed_macs.copy()
                self._changed_macs.clear()
                removed = self._removed_macs.copy()
                self._removed_macs.clear()
                if self.connected and (changed or removed):
                    self.log.info(f'UPDATING TAGS: changed={changed}, removed={removed}')
                    await self.broadcast_changed_tags(changed, removed)
        self.log.warning('websocket sender ended')

    async def receiving(self):
        '''
        websocket receive requests from web page
        '''
        self.log.info('WS:{} websocket receiving started'.format(websocket.id))
        while not self._exit:
            data = await websocket.receive_json()
            await self.ws_process(data)      
        self.log.warning('WS:{} websocket receiving ended'.format(websocket.id))
        
    async def broadcast_updates(self, update, type='sync_state'):
        '''
        broadcast filename changes to all websockets connected
        '''
        data={'type':type, 'data': update}
        for websoc in self.connected:
            await self.ws_send(data, websoc)
                
    async def ws_process(self, data):
        '''
        process and respond to websocket data request
        '''
        if data.get('type') != 'pong':
            self.log.info(f'WS({websocket.id}): received from ws: {data}')
        else:
            self.log.debug(f'WS({websocket.id}): received from ws: {data}')

        match data['type']:
            case 'pong':
                pass    # ignore pong keepalive
                
            case 'form_submit':
                # process submitted form
                payload = data["payload"]
                await self.process_form_data(payload)
                
            case 'template_preview':
                # update modal fields with default ones from template
                payload = data["payload"]
                mac = payload['mac']
                template = payload['template']
                # Get template default vars
                default_vars = get_value_from_template('vars', self.templates[template], {})
                # Merge: template defaults + current form values
                merged_vars = {k:payload.get(k, default_vars[k]) for k in default_vars.keys()}   # preserves name + current edits 
                # Temporarily update template (no persistence yet)
                new_tag_vars = {"vars": merged_vars, "template": template, 'version': self.get_version(mac)}
                html = await render_template("modal.html", mac=mac, values=new_tag_vars.copy(), templates=self.get_valid_templates(mac))
                await self.ws_send({'type': "replace_modal", 'data': {'mac':mac, 'html':html}})
                
            case _:
                self.log.info('No match for data type: {}'.format(data['type']))
        
    async def ws_send(self, data, websoc=None):
        '''
        send json to websocket
        '''
        try:
            ws = websoc or websocket
            if not self.debug and data.get('type')!='ping':
                self.log.info(f'WS({ws.id}): sending: type: {data.get('type')}, data: {str(data.get('data', data))[:200]}...')
            self.log.debug(f'WS({ws.id}): sending: {data}')
            await ws.send_json(data)
        except Exception as e:
            self.log.exception(e)
        
    def get_ws_id(self):
        '''
        returns next sequential ws id as an integer, with id's being resued when disconnected
        just for logging id's
        '''
        used = [ws.id for ws in self.connected]
        return [x for x in range(1, len(used)+2) if x not in used][0]
        
    async def ws(self):
        '''
        start websocket - receiving only; sending is handled by the single global sender task.
        NOTE: websocket is a context based global, so each websocket variable refers to its own context.
        '''
        try:
            websocket.id = self.get_ws_id()
            ws_obj = websocket._get_current_object()
            self.connected.add(ws_obj)
            self.log.info(f'WS:{websocket.id}, (total:{len(self.connected)}) websocket connected')
            await self.send_full_sync(ws_obj)
            await self.receiving()
        except asyncio.exceptions.CancelledError:
            self.log.info(f'WS({websocket.id}): websocket cancelled')
        except Exception as e:
            self.log.exception(e)
        finally:
            self.log.info(f'WS({websocket.id}): websocket disconnected')
            self.connected.discard(websocket._get_current_object())
        self.log.warning(f'WS({websocket.id}): websocket closed')
        
    async def process_form_data(self, data):
        '''
        process updated form data
        '''
        data = dict(data)  # convert ImmutableMultiDict to normal dict
        self.log.info(f'got form data: {data}')
        mac = data.pop('mac',None)
        name = data.get('name', mac)
        topic = f'{name}/vars'
        if self.callback:
            await self.callback(topic, json.dumps(data))
            
    def get_valid_templates(self, mac):
        '''
        return valid template names for tag
        '''
        return self._data[mac].templates.keys()
        
    def natural_key(self, name):
        '''
        natural key for sorting by name, instead of ascii value
        '''
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', name)]
    
    def get_data(self):
        '''
        get tag names/values from self.tag_vars, add version as jpg file mtime, sort by names order
        '''
        self.log.info(f'displaying Tags for: {self.tag_vars.keys()}')
        data = {}
        for mac, values in self.tag_vars.items():
            v = self.get_version(mac)
            data[mac] = {'vars': values['vars'].copy(), 'version': v, 'valid_templates': self.get_valid_templates(mac), 'template': values['template']}
        # sort by name
        sorted_data = dict(sorted(data.items(), key=lambda item: self.natural_key(item[1]['vars']['name'])))
        self.log.debug(f'sorted data: {sorted_data}')
        return sorted_data
        
    async def show_tags(self):
        '''
        construct tags page from files in static folder
        '''
        self.log.info('loading tags page')
        tag_data = self.get_data()
        self.log.info(f'rendering: {tag_data}')
        return await render_template('index.html', names=tag_data, ap_ip=self.ap_ip)

    async def show_editor(self):
        return await render_template('editor.html')

    async def api_templates(self):
        '''GET /api/templates — return all templates with factory flag'''
        result = {}
        for name, tmpl in self.factory_templates.items():
            result[name] = {'template': tmpl, 'factory': True}
        for name, tmpl in self.user_templates.items():
            result[name] = {'template': tmpl, 'factory': False}
        return jsonify(result)

    def _reload_tag_templates(self):
        '''Refresh each TAG's template list after TEMPLATES has been mutated.'''
        # Reset instance templates back to the global TEMPLATES so get_BWR_Templates()
        # filters from the updated source, not the stale old BWR_Templates copy.
        TAG.BWR_Templates = {}
        for mac in self._data:
            try:
                self._data[mac].templates = TEMPLATES
                self._data[mac].get_BWR_Templates()
                self._data[mac].load_templates()
            except Exception as e:
                self.log.warning(f'reload_tag_templates {mac}: {e}')

    async def _process_template_images(self, template_data: list, template_name: str) -> list:
        '''
        Walk template elements, find image entries with a _src_id sidecar,
        resize to the declared w/h, save locally, upload to AP, replace filename.
        Returns a new template list with _src_id keys stripped.
        '''
        TEMPLATE_IMAGES_DIR.mkdir(exist_ok=True)
        img_index = 0
        out = []
        for item in template_data:
            if 'image' not in item:
                out.append(item)
                continue
            params = list(item['image'])           # [filename, x, y] + optional _src_id, w, h
            src_id = item.get('_src_id')
            tgt_w  = item.get('_img_w')
            tgt_h  = item.get('_img_h')
            # Build a safe AP filename: {template}_{index}.jpg
            safe_name = re.sub(r'[^A-Za-z0-9_\-]', '_', template_name)
            ap_filename = f'{safe_name}_{img_index}.jpg'
            img_index += 1
            if src_id and tgt_w and tgt_h:
                src_path = TEMPLATE_IMAGES_DIR / f'{src_id}_src.jpg'
                if src_path.exists():
                    try:
                        img = Image.open(src_path).convert('RGB')
                        img = img.resize((int(tgt_w), int(tgt_h)), Image.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, 'JPEG', quality=85)
                        jpeg_bytes = buf.getvalue()
                        # Save resized copy locally
                        local_path = TEMPLATE_IMAGES_DIR / ap_filename
                        local_path.write_bytes(jpeg_bytes)
                        await self._upload_image_to_ap(ap_filename, jpeg_bytes)
                        params = [ap_filename, params[1] if len(params) > 1 else 0,
                                              params[2] if len(params) > 2 else 0]
                        self.log.info(f'Processed image {ap_filename} ({tgt_w}x{tgt_h})')
                    except Exception as e:
                        self.log.error(f'Image processing failed for {src_id}: {e}')
            entry = {'image': params}
            # Persist dimensions so editor can restore correct size on reload
            if tgt_w: entry['_img_w'] = tgt_w
            if tgt_h: entry['_img_h'] = tgt_h
            out.append(entry)
        return out

    async def api_template(self, name):
        '''POST /api/templates/<name> — save; DELETE — delete. Factory templates are read-only.'''
        if request.method == 'POST':
            if name in self.factory_templates:
                return jsonify({'error': 'Cannot overwrite a factory template'}), 403
            data = await request.get_json()
            data = await self._process_template_images(data, name)
            self.user_templates[name] = data
            TEMPLATES[name] = data
            save_user_templates(self.user_templates)
            self._reload_tag_templates()
            self.log.info(f'Saved user template: {name}')
            return jsonify({'ok': True})

        elif request.method == 'DELETE':
            if name in self.factory_templates:
                return jsonify({'error': 'Cannot delete a factory template'}), 403
            if name not in self.user_templates:
                return jsonify({'error': 'Template not found'}), 404
            del self.user_templates[name]
            TEMPLATES.pop(name, None)
            save_user_templates(self.user_templates)
            self._reload_tag_templates()
            self.log.info(f'Deleted user template: {name}')
            return jsonify({'ok': True})

    async def api_images_stage(self):
        '''POST /api/images/stage — receive a local file upload, save as source, return preview info.'''
        TEMPLATE_IMAGES_DIR.mkdir(exist_ok=True)
        files = await request.files
        f = files.get('file')
        if f is None:
            return jsonify({'error': 'No file provided'}), 400
        data = f.read()
        src_id = hashlib.sha1(data).hexdigest()[:16]
        src_path = TEMPLATE_IMAGES_DIR / f'{src_id}_src.jpg'
        try:
            img = Image.open(io.BytesIO(data)).convert('RGB')
            img.save(src_path, 'JPEG')
            w, h = img.size
        except Exception as e:
            return jsonify({'error': f'Invalid image: {e}'}), 400
        self.log.info(f'Staged image {src_id} ({w}x{h})')
        return jsonify({'id': src_id, 'url': f'/api/images/src/{src_id}', 'width': w, 'height': h})

    async def api_images_src(self, src_id):
        '''GET /api/images/src/<id> — serve a staged source image for editor preview.'''
        # Sanitise: only hex chars allowed
        if not all(c in '0123456789abcdef' for c in src_id):
            return jsonify({'error': 'Invalid id'}), 400
        path = TEMPLATE_IMAGES_DIR / f'{src_id}_src.jpg'
        if not path.exists():
            return jsonify({'error': 'Not found'}), 404
        response = await make_response(path.read_bytes())
        response.headers['Content-Type'] = 'image/jpeg'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    async def api_images_ap_list(self):
        '''GET /api/images/ap_list — proxy AP /edit?list=/ and return jpg/png filenames.'''
        if not self.ap_ip:
            return jsonify([])
        try:
            data = await self._ap_request('get', 'edit?list=/')
            files = []
            if isinstance(data, list):
                files = [e['name'].lstrip('/') for e in data
                         if isinstance(e, dict) and e.get('name', '').lower().endswith(('.jpg', '.jpeg', '.png'))]
            elif isinstance(data, dict):
                files = [e['name'].lstrip('/') for e in data.get('files', [])
                         if isinstance(e, dict) and e.get('name', '').lower().endswith(('.jpg', '.jpeg', '.png'))]
            return jsonify(sorted(files))
        except Exception as e:
            self.log.warning(f'ap_list error: {e}')
            return jsonify([])

    async def _upload_image_to_ap(self, filename: str, jpeg_data: bytes):
        '''Upload a JPEG to the AP filesystem via POST /edit (SPIFFSEditor).'''
        if not self.ap_ip:
            self.log.warning('No AP configured — skipping image upload')
            return
        form = aiohttp.FormData()
        form.add_field('data', jpeg_data,
                       filename=filename,
                       content_type='image/jpeg')
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            url = f'http://{self.ap_ip}/edit'
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            async with self._session.post(url, data=form, timeout=timeout) as resp:
                if resp.status in (200, 201):
                    self.log.info(f'Uploaded {filename} to AP ({len(jpeg_data)} bytes)')
                else:
                    text = await resp.text()
                    self.log.error(f'AP image upload failed {resp.status}: {text}')
        except Exception as e:
            self.log.error(f'AP image upload exception: {e}')

    async def api_images_ap_proxy(self, filename):
        '''GET /api/images/ap_proxy/<filename> — fetch a file from AP FS and return it.
        Used by editor to preview images already stored on the AP.'''
        if not self.ap_ip:
            return jsonify({'error': 'No AP configured'}), 404
        # Try local cache first
        local = TEMPLATE_IMAGES_DIR / filename
        if local.exists():
            response = await make_response(local.read_bytes())
            response.headers['Content-Type'] = 'image/jpeg'
            return response
        try:
            data = await self._ap_request('get', f'edit?download=/{filename}', is_binary=True)
            if not data:
                return jsonify({'error': 'Not found on AP'}), 404
            response = await make_response(data)
            response.headers['Content-Type'] = 'image/jpeg'
            response.headers['Cache-Control'] = 'no-cache'
            return response
        except Exception as e:
            self.log.error(f'ap_proxy error: {e}')
            return jsonify({'error': str(e)}), 500


class TAG(UserDict):
    '''
    class containg all the data and methods for one tag
    '''
    
    scaling = {'text'       : {(0,)     :'H', (1,6)     :'V', (3,)  :'F'},
               'textbox'    : {(0,2)    :'H', (1,3,7)   :'V', (5,)  :'F'},
               'box'        : {(0,2)    :'H', (1,3)     :'V', (6,)  :'borderwidth'},
               'rbox'       : {(0,2,6)  :'H', (1,3)     :'V', (4,7) :'R/borderwidth'},
               'line'       : {(0,2)    :'H', (1,3)     :'V'},
               'triangle'   : {(0,2,4)  :'H', (1,3,5)   :'V'},
               'circle'     : {(0,)     :'H', (1,)      :'V', (2,)  :'R'},
               'image'      : {(1,)     :'H', (2,)      :'V'},
               'default'    : {(0,2)    :'H', (1,3)     :'V'},
              }
              
    templates = TEMPLATES
    BWR_Templates = {}
    
    def __init__(self, mac, data, tag_images, ap_callback, update_vars_callback):
        self.log = logging.getLogger('Main.'+__class__.__name__)
        self.debug = self.log.getEffectiveLevel() <= logging.DEBUG
        self.mac = mac
        self.data = data
        self.tag_images = tag_images
        self.ap_callback = ap_callback
        self.update_vars_callback = update_vars_callback
        self.tag_json = []
        self.current_template_key="Empty"
        self.first_template = None
        self.get_BWR_Templates()
        # NOTE: "textbox" does not work with tt fonts (so dosent work with fonts/calibrib<size> as this gets switched to a tt font internally)
        #       bgcolor (variable 7 of "text") only works with vfw fonts (actually doesnt work at all)
        #       fonts/calibrib50, fonts/calibrib20 are bitmap fonts (number is the size) is the same as Signika-SB.ttf with size parameter (because it gets switched internally)
        #       except size 16 and 30 as these sizes are directly implemented as calibrib16 and calibrib30. you need "fonts/calibrib20" not just "calibrib20" due to a bug in the AP FW
        # also:
        # bahnschrift20.vlw upper case, lower case, numbers, and äöüßÄÖÜåÅ!\"#$%&'()*+,-./:;<=>?@[\\]^_{|}~°
        # bahnschrift30.vlw upper case, lower case, numbers, and äöüßÄÖÜåÅ!\"#$%&'()*+,-./:;<=>?@[\\]^_{|}~°
        # bahnschrift70.vlw only 0123456789.
        # calibrib30.vlw upper case, lower case, numbers, and äöüßÄÖÜåÅ!\"#$%&'()*+,-./:;<=>?@[\\]^_{|}~°
        # twcondensed20.vlw Only SUMOTWEHFRAZDIV0123456789. Use for weekday names and numbers.
        # see https://atc1441.github.io/oepl_json_designer/

        self.default_template = [{ "text": [125, 15, "{fil}", "Signika-SB.ttf", "black", 1, 50] },
                                 { "rbox": [-10, 80, 90, 58, 10,"black"] },
                                 { "rbox": [100, 80, 180, 58, 10, "red"] },
                                 { "text": [5, 90, "{color}", "Signika-SB.ttf", "white", 0, 20] },
                                 { "text": [245, 90, "{pct}%", "Signika-SB.ttf", "white", 2, 20] },
                                 { "bars": [115, 90, 80, 20, "white","{pct}"] },
                                 { "vars": {"pct": "100", "color": "White", "fil": "PLA"} }, #defaults
                                 { "size": {"width": 250, "height": 122 }},
                                 {"template": "AMS Tags"}] 
        self.load_templates()
        
    def load_templates(self):
        try:
            self.templates = self.get_valid_templates()
            self.log.info(f'loaded {len(self.templates)} templates for {self.mac}')
            self.first_template = next(iter(self.templates))
            self.default_template = self.templates.get(self.first_template, self.default_template)
        except Exception as e:
            self.log.error(f'Error in: {TEMPLATES}')
            self.log.exception(e)
            
    def get_valid_templates(self):
        hw_type = self.data.get('hw_type')
        self.log.debug(f'hw_type: {hw_type}')
        is_bwry = hw_type in range(208, 223)   # 208..223, all Wolink BWRY types
        return self.templates if is_bwry else self.BWR_Templates
            
    def get_BWR_Templates(self):
        '''
        make dict of templates that are not BWRY, and update class BWR_Templates variable
        '''
        if not self.BWR_Templates:
            valid_templates = {}
            for name, vals in self.templates.items():
                skip = False
                for line in vals:
                    values = next(iter(line.values()))
                    if not isinstance(values, list):
                        continue
                    if any(['yellow' in item.lower() for item in values if isinstance(item, str)]):
                        skip = True
                if not skip:
                    self.BWR_Templates[name] = vals
            
    def save_tag():
        self.log.debug(f'saving {self.mac}')
        filepath=Path(f'./current/{self.mac}.json')
        try:
            if filepath.is_file():
                self.log.debug(f'SAVING: {filepath}')
                with open(filepath, 'w') as f:
                    json.dump(self.data, f, indent=2) 
        except Exception:
            pass
            
    def get_data(self, value=None, default=None):
        return self.data if value is None else self.data.get(value, default)
            
    def get_name(self):
        '''
        get name of tag
        '''
        return self.data.get('tag_name', self.mac)
            
    def get_template_line(self, line):
        '''
        gets key, value, where value is a list or dict from a template line
        '''
        key = value = None
        try:
            key, value = next(iter(line.items()))
        except Exception as e:
            pass
        return key, value
                                 
    def get_size(self):
        '''Raw buffer dimensions from the tag DB — used for image decoding.'''
        width = self.data.get("width")
        height = self.data.get("height")
        return width, height

    def get_display_size(self):
        '''Visible display dimensions — applies DISPLAY_SIZE_OVERRIDES for template scaling.'''
        hw_type = self.data.get("hw_type")
        overrides = DISPLAY_SIZE_OVERRIDES.get(hw_type, {})
        width, height = self.get_size()
        return overrides.get('width', width), overrides.get('height', height)
        
    def scale_template(self, template):
        '''
        Return a scaled copy of template without mutating inputs.
        '''
        width, height = self.get_display_size()

        # Find template size
        size_line = get_value_from_template('size', template)

        if not size_line:
            self.log.warning("no size found in template - not scaling")
            return template

        scale = (
            width / size_line["width"],
            height / size_line["height"],
        )

        if scale == (1, 1):
            return template

        def scale_line(line):
            key, value = self.get_template_line(line)
            if isinstance(value, list):
                scaled = [self.scale_val(key, i, v, scale) for i, v in enumerate(value)]
                result = {key: scaled}  # OEPL key first, then sidecar keys
                result.update({k: v for k, v in line.items() if k != key})
                # Scale stored image dimensions too
                if key == 'image':
                    if '_img_w' in result: result['_img_w'] = int(result['_img_w'] * scale[0])
                    if '_img_h' in result: result['_img_h'] = int(result['_img_h'] * scale[1])
                return result
            return line

        scaled_template = [scale_line(line) for line in template]

        self.log.debug("RETURNING Scaled Template: %s", scaled_template)
        return scaled_template
    
    def scale_val(self, key, pos, val, factor):
        '''
        Scale value using lookup dictionary self.scaling.
        '''
        scale_map = self.scaling.get(key, self.scaling["default"])

        direction = next(
            (d for positions, d in scale_map.items() if pos in positions),
            None,
        )

        if direction is None:
            return val

        if not isinstance(val, (int, float)):
            return val

        if direction == "H":
            f = factor[0]
        elif direction == "V":
            f = factor[1]
        elif direction == "F":
            def multiply_match(match):
                """
                Callback function to multiply the found number by vertical factor.
                """
                number = int(match.group(0))
                return str(int(number * factor[1]))
            if val.startswith('fonts/calibrib'):
                self.log.debug("SCALING FONT %s", val)
                val = re.sub(r'\d+', multiply_match, val)
                self.log.debug("FONT SCALED to %s", val)
            return val                
        else:
            f = min(factor)

        result = int(val * f)
        self.log.debug(
            "SCALING %s %s by %s from %s to %s",
            key, direction, f, val, result,
        )
        return result
        
    async def get_curent_data(self):
        '''
        gets the tags json from ap
        '''
        current = await self.ap_callback('get', f'current/{self.mac}.json')
        if current:
            self.tag_json = current
            self.log.info(f'self.tag_json: {self.tag_json}')
            template_key = get_value_from_template('template', current)
            # update web tag_vars dict with current vars, including the current tag template
            if not template_key:
                self.log.warning(f'no template key in AP json for {self.mac} - defaulting to Empty')
                template_key = 'Empty'
            self.current_template_key = template_key
            # Fetch and save the image BEFORE notifying the UI, so the browser
            # gets the new jpg when it reloads the tag card image.
            await self.get_curent_image(current)
            await self.update_vars_callback(self.mac, {'vars':get_value_from_template('vars', current, {}), 'template':template_key})
            return current
        return []
        
    async def get_curent_image(self, current):
        try:
            if self.tag_images and self.tag_images.is_dir():  # if directory is set for images to be stored in
                raw = await self.ap_callback('get', f'current/{self.mac}.raw', is_binary=True)
                self.log.info(f'got raw image: {self.mac}: {len(raw)} bytes')
                if raw:
                    self.save_jpg_img(raw, current)
        except Exception as e:
            self.log.exception(e)
            
    def insert_separator(self, s, sep):
        '''
        make tag bar code format ie 92135733 to 92.13.57.33
        '''
        return s if len(s) <= 2 else s[:2] + sep + self.insert_separator(s[2:], sep)
        
    def make_bar_code_image(self, width, height, code_height=30):
        '''
        make bar code image code_height pixels taller than the tag image (because it will be rotated 90 degrees)
        tag image will be pasted over this image
        '''
        def get_next_number(s, index=0):
            while True and s:
                char = s[(index:= index+1) % len(s)]    # Use modulo operator for wrapping
                if char.isdigit():
                    yield max(2,int(char)//1.3)
            
        bar_code_txt = self.insert_separator(self.mac[-8:], '.')
        bar_code_img = Image.new('RGB', (height, width+(2*code_height)), color="white")    # make white image code_height pixels taller than tag image
        draw = ImageDraw.Draw(bar_code_img)
        font = ImageFont.load_default()
        # get text size
        bbox = draw.textbbox((0, 0), bar_code_txt, font=font, anchor='lt')
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        # The text() method takes the position (xy - top left), the text string, the color (black), and the font. start with text centred + current_x/2
        draw.text(((height/2-text_width/2)+10, code_height-text_height-code_height//3), bar_code_txt, fill="black", font=font)
        # draw fake bar code
        next_num = get_next_number(self.mac)
        bar_height = code_height//3
        current_x = 20
        while current_x < height:
            bar_width = next(next_num)
            space_width = next(next_num)
            draw.rectangle([current_x, 0, current_x + bar_width, bar_height], fill="black")
            current_x += bar_width + space_width
        bar_code_img = bar_code_img.transpose(Image.ROTATE_270) #rotate 90 degrees clockwise
        return bar_code_img
    
    def make_wolink_image(self, width, height, case_width=30):
        '''
        make wolink image case_width pixels taller than the tag image
        tag image will be pasted over this image
        '''
        case_img = Image.new('RGB', (width+(2*case_width), height), color="white")    # make white image code_height pixels wider than tag image
        draw = ImageDraw.Draw(case_img)
        draw.rectangle([7, 8, 15, 18], fill="blue", outline="black", width=1)  # draw LED
        return case_img
        
    def save_jpg_img(self, data, current):
        '''
        save raw image as jpg using mac.jpg as the filename
        '''
        width, height = self.get_size()
        total_pixels = width * height
        plane_size = (total_pixels + 7) // 8   # ceil division fix
        filename = self.tag_images / f'{self.mac}.jpg'
        black_plane = data[:plane_size]

        hw_type = self.data.get('hw_type')
        self.log.info(f'size: {width}x{height}, hw_type: {hw_type}')
        is_bwry = hw_type in range(208, 223)   # 208..223, all Wolink BWRY types

        img = np.ones((height, width, 3), dtype=np.uint8) * 255

        if is_bwry:
            # BWRY format: row-major, no flip
            # Encoding: plane0=0,plane1=0=black; 1,0=white; 0,1=yellow; 1,1=red
            color_plane = data[plane_size:plane_size * 2] if len(data) >= plane_size * 2 else None
            pixel_index = 0
            for i in range(plane_size):
                for bit in range(8):
                    if pixel_index >= total_pixels:
                        break
                    y = pixel_index // width
                    x = pixel_index % width
                    black_bit = (black_plane[i] >> (7 - bit)) & 1
                    color_bit = (color_plane[i] >> (7 - bit)) & 1 if color_plane is not None else 0
                    if black_bit == 0 and color_bit == 0:
                        img[y, x] = [0, 0, 0]       # black
                    elif color_bit == 1 and black_bit == 0:
                        img[y, x] = [255, 200, 0]   # yellow
                    elif color_bit == 1 and black_bit == 1:
                        img[y, x] = [255, 0, 0]     # red
                    # else: white (already initialized to 255)
                    pixel_index += 1
        else:
            # Standard BWR format: column-major, vertical flip (rotatebuffer=3)
            red_plane = data[plane_size:] or bytearray([0x0] * plane_size)
            pixel_index = 0
            for i in range(plane_size):
                for bit in range(8):
                    if pixel_index >= total_pixels:
                        break
                    x = pixel_index // height
                    y = pixel_index % height
                    y = height - 1 - y   # vertical flip
                    black_bit = (black_plane[i] >> (7 - bit)) & 1
                    red_bit   = (red_plane[i]   >> (7 - bit)) & 1
                    if black_bit:
                        img[y, x] = [0, 0, 0]
                    elif red_bit:
                        img[y, x] = [255, 0, 0]
                    pixel_index += 1

        tag = Image.fromarray(img)
        width, height = self.get_display_size()
        tag_border = 30 # left/right white space on tag
        if hw_type in range(176, 187):  # Gicisky
            bar_code_background = self.make_bar_code_image(width, height, tag_border)
            bar_code_background.paste(tag, (tag_border, 0))
            tag = bar_code_background
        elif is_bwry: # Wolink
            background = self.make_wolink_image(width, height, tag_border)
            background.paste(tag, (tag_border, 0))
            tag = background
        tag.save(filename)
        self.log.info(f'wrote image {filename}')
        
    def make_bars(self, v_list, vars=None):
        '''
        make progress bar as "box" from bars entry
        '''
        vars = vars or {}

        x, y, w, h, c, var, *rest = v_list
        direction = rest[0] if rest else 0
        key = var.strip("{}")

        try:
            val = int(vars[key])
        except (KeyError, ValueError, TypeError):
            self.log.warning("No %s found in %s", var, vars)
            return []

        val = max(0, min(100, int(val)))    # clamp val
        pos = (w * val) // 100
        step = max(1, w // 10)
        bw = max(1, w // 20)

        if pos == 0:
            return []

        if direction == 1:
            # right-to-left: fill from right edge inward
            return [
                {"box": [x0, y, bw, h, c]}
                for x0 in range(x + w - pos, x + w, step)
            ]
        return [
            {"box": [x0, y, bw, h, c]}
            for x0 in range(x, x + pos, step)
        ]
        
    def get_and_update_existing_vars(self, tag, vars, template=None):
        """
        find 'vars' in tag json, update them with new values, and return updated vars.
        if 'vars' doesn't exist, add it to the tag.
        If template is supplied, restrict merged vars to keys defined in the template
        so that stale vars from old templates are not carried forward.
        Pure-functional:
        - does not mutate tag or vars
        - returns (new_tag, merged_vars)
        """
        # Determine the canonical set of var keys from the template, if available
        template_vars = None
        if template:
            t_vars_entry = next((l for l in template if 'vars' in l), None)
            if t_vars_entry:
                template_vars = t_vars_entry['vars']

        merged_vars = None
        new_tag = []

        for line in tag:
            if "vars" in line and merged_vars is None:
                merged_vars = {**line["vars"], **vars}
                if template_vars is not None:
                    # Keep only keys the template knows about; fill missing with template defaults
                    merged_vars = {k: merged_vars.get(k, template_vars[k]) for k in template_vars}
                new_tag.append({"vars": merged_vars})
            else:
                new_tag.append(line)

        if merged_vars is None:
            merged_vars = dict(vars)
            new_tag.append({"vars": merged_vars})

        return new_tag, merged_vars
        
    async def make_tag(self, vars=None, template_key=None):
        '''
        make new tag for mac from vars, using vars in template as defaults.
        template is loaded from int, template_key, or template_key if its a template itself
        update vars in new tag as defaults and return new tag json
        Pure-functional version:
        - does not mutate template, vars, or intermediate structures
        - constructs a new tag from immutable transformations
        '''
        current_tag = current_template = None
        vars = vars or {}
        # Resolve template
        if not template_key:
            current_tag = await self.get_curent_data()
            current_template = template_key = get_value_from_template('template', current_tag, self.current_template_key)
            
        if isinstance(template_key, list):
            template = template_key
        elif isinstance(template_key, str):
            template = self.templates.get(template_key)
            
        current_tag = current_tag or await self.get_curent_data()
        if not current_tag:
            self.log.warning(f"no current tag values - using defaults from template {template}")
            current_tag = template
            
        if not any([True for item in current_tag if 'template' in item.keys()]):
            current_tag.append({'template': template_key})
            self.log.warning(f'added template key to current tag {template_key}')
            
        if current_template != template_key:
            self.log.warning(f'changing template from {current_template} to {template_key}')
            current_tag = self.templates.get(template_key)
            self.current_template_key = template_key

        # vars updated functionally; pass template so stale vars are pruned
        current_tag, vars = self.get_and_update_existing_vars(current_tag, vars, template=template)

        def substitute_vars(key, value):
            """Return a new value list with variables substituted."""
            if not isinstance(value, list):
                return value

            def replace(item):
                if not isinstance(item, str):
                    return item
                for var, val in vars.items():
                    if var == 'name':               # auto update name if in vars
                        val = self.get_name()
                    placeholder = f"{{{var}}}"
                    if placeholder in item:
                        #if not str(val).strip():
                        #    val = vars.get(val, '') # use default if no value
                        self.log.debug(f'replaced {placeholder} with {str(val).strip()}')
                        return item.replace(placeholder, str(val).strip())
                return item

            return [replace(item) for item in value]

        def build_line(line):
            """Return new tag lines generated from one template line."""
            key, value = self.get_template_line(line)

            if key == "bars":
                return self.make_bars(value, vars)

            new_value = substitute_vars(key, value)
            return [{key: new_value}]

        scaled_template = self.scale_template(template)

        # Flatten lines returned by build_line
        new_tag = [
            line
            for template_line in scaled_template
            for line in build_line(template_line)
        ]

        new_tag, vars = self.get_and_update_existing_vars(new_tag, vars)

        # Ensure the template key is always present so get_curent_data can find it
        if template_key and not any('template' in item for item in new_tag):
            new_tag.append({'template': template_key})

        self.log.info("RETURNING NEW TAG: %s", new_tag)
        #if new_tag:
        #    self.save_tag()
        return new_tag, vars
    

class EPaper(WEB):
    
    def __init__(self, ap,
                       folder=None,
                       server="192.168.100.16",
                       port=1883,
                       login="",
                       password="",
                       topic=None):
        self.log = logging.getLogger('Main.'+__class__.__name__)
        self.debug = self.log.getEffectiveLevel() <= logging.DEBUG
        super().__init__(Path(folder), ap, self.handle_mqtt_msg)
        self.host = ap
        self.tag_images = Path(folder)
        self.server = server
        self.port = port
        self.login = login
        self.password = password
        self.topic = f'{topic}/data'
        self.subscribe_topic = f'{topic}/command/#'      
        self.client = None
        self.online = False
        self._storage_file = TAG_FILE
        self._session = None
        self.exit = False
        self._last_record_count = None
        self._tag_manager = None
        self._blacklisted_tags = []
        self._known_tags = set()
        self._ap_data = {}
        self._data = {}
        self._last_saved = {}
        self.tasks = set()
        self.add_signals()       
        validate_templates()
        
    def new_tag(self, mac, data):
        '''
        return new tag object
        '''
        return TAG(mac, data, self.tag_images, self._ap_request, self.update_vars)
    
    def add_signals(self):
        '''
        setup signals to exit program
        '''
        try:    #might not work on windows
            asyncio.get_running_loop().add_signal_handler(SIGINT, self.close)
            asyncio.get_running_loop().add_signal_handler(SIGTERM, self.close)
        except Exception:
            self.log.warning('signal error')
            
    async def run(self):
        self._session = aiohttp.ClientSession()
        self._tag_manager = await get_tag_types_manager()
        self.add_task(self.start_mqtt_server())
        self._ws_task = self.add_task(self._websocket_handler())
        try:
            await self.async_load_all_tags()
        except Exception as e:
            self.load_tags()
        self.add_task(self.serve_forever())
        while not self.exit:
            await asyncio.sleep(1)
        if self._session and not self._session.closed:
            await self._session.close()
            
    def close(self):
        '''
        exit server
        '''
        self.log.info('SIGINT/SIGTERM received, exiting')
        self.exit=True
        super().close()
        [task.cancel() for task in self.tasks if not task.done()]
        
    def add_task(self, callback):
        '''
        add callback task to self.tasks and run as a background task (if it's not a Dummy instance)
        '''
        try:
            task = asyncio.create_task(callback)
            self.tasks.add(task)
            task.add_done_callback(self.tasks.remove)
            return task
        except Exception as e:
            self.log.warning(f'task error: {e}')
        return None
        
    def save_tags(self):
        '''
        save tag database
        '''
        try:
            data = {mac:tag.get_data() for mac, tag in self._data.items()}
            if data != self._last_saved:
                with open(self._storage_file, "w") as f:
                    json.dump(data, f, indent=4)
                self._last_saved = data
        except Exception as err:
            self.log.warning("Error saving tags to storage: %s", err, exc_info=True)
            
    def load_tags(self):
        '''
        load tag database
        '''
        try:
            with open(self._storage_file, "r") as f:
                tags = json.load(f)
                for mac, data in tags.items():
                    self._data[mac] = self.new_tag(mac, data)
                self._known_tags = set(self._data.keys())
                self._last_saved = {mac:tag.get_data() for mac, tag in self._data.items()}
        except Exception as err:  # pragma: no cover - defensive
            self.log.warning("Error loading tags from storage: %s", err, exc_info=True)
            
    def get_mac(self, name):
        '''
        get mac from name
        '''
        try:
            for mac, tag in self._data.items():
                if tag.get_name() == name:
                    return mac
        except Exception as e:
            self.log.exception(e)
        self.log.warning("mac not found in tag database")
        return name
        
    def get_name(self, mac):
        '''
        get name from mac
        '''
        if mac in self._data.keys():
            return self._data[mac].get_name()
        return mac
        
    async def start_mqtt_server(self):
        '''
        main loop should not exit until SIGINT received.
        '''
        self.client = aiomqtt.Client(self.server, port=self.port, username=self.login, password=self.password)
        interval = 5  # Seconds
        while not self.exit:
            self.log.info('connecting to MQTT broker: {}:{}'.format(self.server, self.port))
            try:
                async with self.client:
                    # Subscribe to the command topic
                    await self.client.subscribe(self.subscribe_topic)
                    self.log.info(f"Subscribed to topic: {self.subscribe_topic}")
                    async for message in self.client.messages:
                        self.log.debug('received topic: {}, message: {}'.format(message.topic, message.payload.decode('UTF-8')))
                        await self.handle_mqtt_msg(message.topic.value, message.payload.decode('UTF-8'))
                                
            except aiomqtt.MqttError:
                self.log.warning(f"Connection to MQTT broker lost; Reconnecting in {interval} seconds ...")
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                self.log.info('cancelled')
            except Exception as e:
                self.log.exception(e)
                await asyncio.sleep(interval)
                
        self.log.info('exiting')
        
    async def publish(self, topic=None, msg=None):
        '''
        publish message
        '''
        try:
            if self.client and msg is not None:
                topic = f'{self.topic}/{topic}' if topic else self.topic
                if isinstance(msg, dict):
                    msg = json.dumps(msg)
                await self.client.publish(topic, payload=msg)
                self.log.info('published: {}, {}'.format(topic, msg))
            else:
                self.log.warning('not publishing {}, {}'.format(self.topic, msg))
        except aiomqtt.exceptions.MqttCodeError as e:
            self.log.exception(e)
            await self.reboot_ap()
            self.close()
            
    async def initialize_tag(self, tag_mac, current_tag=None):
        tag = self._data[tag_mac]
        if current_tag is None:
            current_tag = await tag.get_curent_data()
        if not current_tag:
            self.log.warning(f'No json info found for {tag_mac}')
            filepath=Path(f'./current/{tag_mac}.json')
            try:
                if filepath.is_file():
                    self.log.warning(f'UPLOADING: {filepath}')
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                else:
                    self.log.warning(f'file not found {filepath} - initializeing as Empty')
                    data, vars = await tag.make_tag(vars={"name" : tag.get_name()}, template_key="Empty")
                await self.upload_data(tag_mac, json.dumps(data), '19')
                
            except Exception as e:
                self.log.warning(f'error loading tag json: {filepath}: {e}')
            
    async def send_tag_cmd(self, mac: str, cmd: str):
        await self._ap_request("post", "tag_cmd", data={"mac": mac.upper(), "cmd": cmd})
        self.log.info("Sent %s command to %s", cmd, mac)

    async def reboot_ap(self):
        await self._ap_request("post", "reboot")
        self.log.info("Rebooted OEPL AP")
            
    async def _ap_request(self, method: str, path: str, *, data=None, timeout=10, headers={'Connection': 'close'}, is_binary=False):
        '''
        communicate with AP
        '''
        timeout = aiohttp.ClientTimeout(total=timeout)
        url = f"http://{self.host}/{path.lstrip('/')}"
        self.log.debug(f'{method} to url: {url}, data: {data}, headers: {headers}')
        resp = {}
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.request(method, url, data=data, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    self.log.error('failed to %s to AP (status=%s) %s', method, response.status, url)
                else:
                    self.log.info('%s to AP successfull (status=%s) %s', method, response.status, url)
                    resp = await response.json() if not is_binary else await response.read()
        except aiohttp.client_exceptions.ContentTypeError:
            self.log.debug('no content received')
        except asyncio.TimeoutError:
            self.log.warning(f'Timeout on {method} to AP')
            resp = {'timeout':True}
        except aiohttp.client_exceptions.ClientConnectorError as e:
            self.log.error('Connection error on %s: %s', method, e)
        except Exception as err:
            self.log.exception(f'Exception on {method} to AP {err}')
        return resp 
            
    async def _websocket_handler(self) -> None:
        """Handle WebSocket connection lifecycle and process messages.

         This is a long-running task that manages all aspects of the WebSocket
         connection to the OpenEPaperLink Access Point, including:

         - Establishing and maintaining the connection
         - Processing incoming real-time messages from the AP
         - Detecting connection failures and implementing reconnection logic
         - Broadcasting connection state changes to dependent entities

         The handler implements error resilience through nested try/except blocks:

         - Outer block: Handles connection establishment and reconnection
         - Inner block: Processes individual messages within an active connection

         When connection errors occur, the handler waits for RECONNECT_INTERVAL
         seconds before attempting to reconnect, continuing until the hub
         shutdown is signaled via the self._shutdown Event.

         Note: This method should be run as a background task and not awaited
         directly, as it runs indefinitely until shutdown is triggered.
         """
        while not self.exit:
            try:
                ws_url = f"ws://{self.host}/ws"
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url, heartbeat=30) as ws:
                        self.online = True
                        self.log.debug("Connected to websocket at %s", ws_url)

                        # Run verification on each connection to catch deletions that happened while offline
                        await self._verify_and_cleanup_tags()

                        while not self.exit:
                            try:
                                msg = await ws.receive()

                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    await self._handle_message(msg.data)
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    self.log.info("WebSocket error: %s", ws)
                                    break
                                elif msg.type == aiohttp.WSMsgType.CLOSING:
                                    self.log.debug("WebSocket closing")
                                    break
                                elif msg.type == aiohttp.WSMsgType.CLOSED:
                                    self.log.debug("WebSocket closed")
                                    break
                            except asyncio.CancelledError:
                                self.log.debug("WebSocket task cancelled")
                                raise
                            except Exception as err:
                                self.log.error("Error handling message: %s", err)

            except asyncio.CancelledError:
                self.log.debug("WebSocket connection cancelled")
                break
            except aiohttp.ClientError as err:
                self.online = False
                self.log.error("WebSocket connection error: %s", err)
            except Exception as err:
                self.online = False
                self.log.error("Unexpected WebSocket error: %s", err)

            if not self.exit:
                await asyncio.sleep(RECONNECT_INTERVAL)
                
    async def _handle_message(self, message: str) -> None:
        """Process an incoming WebSocket message from the AP.

        Parses the message JSON and routes it to the appropriate handler
        based on the message type:

        - "sys" messages: AP system status updates
        - "tags" messages: Individual tag status updates
        - "logMsg" messages: Log information from the AP
        - "errMsg" messages: Error notifications
        - "apitem" messages: Configuration change notifications

        Args:
            message: Raw WebSocket message string from the AP

        Raises:
            No exceptions are raised as they are caught and logged internally.
        """
        try:
            data = json.loads("{" + message.split("{", 1)[-1])

            if "sys" in data:
                self.log.debug("System message: %s", data["sys"])
                await self._handle_system_message(data["sys"])
            elif "tags" in data:
                self.log.debug("Tag message: %s", data["tags"][0])
                await self._handle_tag_message(data["tags"][0])
            elif "logMsg" in data:
                self.log.debug("OEPL Log message: %s", data["logMsg"])
                await self._handle_log_message(data["logMsg"])
            elif "errMsg" in data:
                await self._handle_log_message(data["errMsg"])
                if data["errMsg"] == "REBOOTING":
                    self.log.debug("AP is rebooting")
                    self._ap_data["ap_state"] = "Offline"
                    self.online = False

                    # Close WebSocket connection immediately
                    if self._ws_task and not self._ws_task.done():
                        self._ws_task.cancel()

                    # Schedule reconnection attempt after brief delay
                    async def delayed_reconnect():
                        await asyncio.sleep(5)
                        if not self.exit:
                            self._ws_task = self.add_task(self._websocket_handler())

                    asyncio.create_task(delayed_reconnect())
                    return
            elif "apitem" in data:
                # Check if this is actually a config change message
                if data.get("apitem", {}).get("type") == "change":
                    await self._handle_ap_config_message(data)
                else:
                    self.log.debug("Ignoring non-change AP message")
            else:
                self.log.debug("Unknown message type: %s", data)

        except json.JSONDecodeError:
            self.log.error("Failed to decode message: %s", message)
        except Exception as err:
            self.log.exception("Error handling message: %s", err)
            
    async def _handle_system_message(self, sys_data: dict) -> None:
        """Process a system message from the AP.

        Updates the AP status information based on system data, including:

        - IP address and Wi-Fi settings
        - Memory usage (heap, database size)
        - Tag counts and AP state
        - Runtime information

        This method is called when the AP sends a "sys" WebSocket message,
        which typically happens periodically or after state changes.

        Args:
            sys_data: Dictionary containing AP system status information
        """

        # Preserve existing values for fields that are not in every message
        current_low_batt = self._ap_data.get("low_battery_count", 0)
        current_timeout = self._ap_data.get("timeout_count", 0)

        self._ap_data = {
            "ip": self.host,
            "sys_time": sys_data.get("currtime"),
            "heap": sys_data.get("heap"),
            "record_count": sys_data.get("recordcount"),
            "db_size": sys_data.get("dbsize"),
            "little_fs_free": sys_data.get("littlefsfree"),
            "ps_ram_free": sys_data.get("psfree"),
            "rssi": sys_data.get("rssi"),
            "ap_state": self._get_ap_state_string(sys_data.get("apstate")),
            "run_state": self._get_ap_run_state_string(sys_data.get("runstate")),
            "temp": sys_data.get("temp"),
            "wifi_status": sys_data.get("wifistatus"),
            "wifi_ssid": sys_data.get("wifissid"),
            "uptime": sys_data.get("uptime"),
            "low_battery_count": sys_data.get("lowbattcount", current_low_batt),
            "timeout_count": sys_data.get("timeoutcount", current_timeout),
        }

        if "recordcount" in sys_data:
            await self._track_record_count_changes(sys_data.get("recordcount", 0))

        await self.publish('system',self._ap_data)

    async def _handle_tag_message(self, tag_data: dict) -> None:
        """Process a tag update message from the AP.

        Updates the stored information for a specific tag based on the
        data received from the AP. This includes:

        - Tag status (battery, temperature, etc.)
        - Scheduling information (next update, next check-in)
        - Signal quality information (RSSI, LQI)

        Args:
            tag_data: Dictionary containing tag properties from the AP
        """
        tag_mac = tag_data.get("mac")
        if not tag_mac:
            return

        # fetch current tag data once; reuse for both publish and initialize
        current_tag = await self.pub_vars(tag_data)

        # Process tag data
        await self._process_tag_data(tag_mac, tag_data)
        self.save_tags()
        if self._data[tag_mac].get_data().get('content_mode') == 'JSON template':
            await self.initialize_tag(tag_mac, current_tag=current_tag)
        await self.publish(self.get_name(tag_mac), self._data[tag_mac].get_data())

    async def _handle_log_message(self, log_msg: str) -> None:
        """Process a log message from the AP.

        Parses log messages for specific events that require action:
        - Block transfer requests: Updates the block_requests counter
        - Transfer completion: Triggers image update notification

        Args:
            log_msg: Raw log message string from the AP
        """
        if "block request" in log_msg:
            # Extract MAC address from block request message
            # Example: "0000000000123456 block request /current/0000000000123456_452783.pending block 0"
            parts = log_msg.split()
            if len(parts) > 0:
                tag_mac = parts[0].upper()
                if tag_mac in self._data:
                    block_requests = self._data[tag_mac].get("block_requests", 0) + 1
                    self._data[tag_mac]["block_requests"] = block_requests
        if "reports xfer complete" in log_msg:
            # Extract MAC address from block request message
            parts = log_msg.split()
            if len(parts) > 0:
                tag_mac = parts[0].upper()
                if tag_mac in self._data:
                    pass
        await self.publish('log', log_msg)

    async def _process_tag_data(self, tag_mac: str, tag_data: dict, is_initial_load: bool = False) -> bool:
        """Process tag data and update internal state.

        Handles updates for a single tag, including:

        - Updating stored tag information
        - Calculating runtime and update counters
        - Managing tag discovery events
        - Broadcasting update events to entities
        - Triggering device events for buttons/NFC (with debouncing)

        Args:
            tag_mac: MAC address of the tag
            tag_data: Dictionary containing tag properties from the AP
            is_initial_load: True if this is part of initial loading at startup,
                             which affects event triggering behavior

        Returns:
            bool: True if this was a newly discovered tag, False for an update

        Raises:
            No exceptions are raised as they are caught and logged internally.
        """

        # Skip blacklisted tags
        if tag_mac in self._blacklisted_tags:
            self.log.debug("Ignoring blacklisted tag: %s", tag_mac)
            return False

        # Check if this is a new tag
        is_new_tag = tag_mac not in self._known_tags

        # Get existing data to calculate runtime and update counters
        existing_data = self._data.get(tag_mac, {})

        tag_name = tag_data.get("alias") or tag_mac
        last_seen = tag_data.get("lastseen")
        next_update = tag_data.get("nextupdate")
        next_checkin = tag_data.get("nextcheckin")
        lqi = tag_data.get("LQI")
        rssi = tag_data.get("RSSI")
        temperature = tag_data.get("temperature")
        battery_mv = tag_data.get("batteryMv")
        pending = tag_data.get("pending")
        hw_type = tag_data.get("hwType")
        hw_string = get_hw_string(hw_type)
        width, height = self._tag_manager.get_hw_dimensions(hw_type)
        content_mode = tag_data.get("contentMode")
        wakeup_reason = self._get_wakeup_reason_string(tag_data.get("wakeupReason"))
        capabilities = tag_data.get("capabilities")
        hashv = tag_data.get("hash")
        modecfgjson = tag_data.get("modecfgjson")
        is_external = tag_data.get("isexternal")
        rotate = tag_data.get("rotate")
        lut = tag_data.get("lut")
        channel = tag_data.get("ch")
        version = tag_data.get("ver")
        update_count = tag_data.get("updatecount")

        # Check if name has changed
        old_name = existing_data.get("tag_name")
        if old_name and old_name != tag_name:
            self.log.debug("Tag name changed from '%s' to '%s'", old_name, tag_name)

        # Calculate runtime delta (only if this is not the initial load)
        runtime_delta = 0
        runtime_total =  existing_data.get("runtime", 0)
        if not is_initial_load and existing_data:
            runtime_delta = self._calculate_runtime_delta(tag_data, existing_data)
            runtime_total += runtime_delta

        # Update boot count if this is a power-on event
        boot_count = existing_data.get("boot_count", 1)
        if not is_initial_load and wakeup_reason in [1, 252, 254]:  # BOOT, FIRSTBOOT, WDT_RESET
            boot_count += 1
            runtime_total = 0  # Reset runtime on boot

        # Update check-in counter
        checkin_count = existing_data.get("checkin_count", 0)
        if not is_initial_load:
            checkin_count += 1

        # Get existing block request count
        block_requests = existing_data.get("block_requests", 0)

        # Update tag data
        new_tag_data = {
            "tag_mac": tag_mac,
            "tag_name": tag_name,
            "last_seen": last_seen,
            "next_update": next_update,
            "next_checkin": next_checkin,
            "lqi": lqi,
            "rssi": rssi,
            "temperature": temperature,
            "battery_mv": battery_mv,
            "pending": pending,
            "hw_type": hw_type,
            "width": width,
            "height": height,
            "hw_string": hw_string,
            "content_mode": self._get_content_mode_string(content_mode),
            "wakeup_reason": wakeup_reason,
            "capabilities": capabilities,
            "hash": hashv,
            "modecfgjson": modecfgjson,
            "is_external": is_external,
            "rotate": rotate,
            "lut": lut,
            "channel": channel,
            "version": version,
            "update_count": update_count,
            "runtime": runtime_total,
            "boot_count": boot_count,
            "checkin_count": checkin_count,
            "block_requests": block_requests,
        }
        if not is_new_tag:    
            self._data[tag_mac].update(new_tag_data)
        else:
            self._data[tag_mac] = self.new_tag(tag_mac, new_tag_data)

        # Handle new tag discovery
        if is_new_tag:
            self._known_tags.add(tag_mac)
            self.log.debug("Discovered new tag: %s", tag_mac)

        return is_new_tag
        
    async def _fetch_all_tags_from_ap(self) -> dict:
        """Fetch complete list of tags from the AP database.

        Retrieves all tag data using the AP's HTTP API, handling pagination
        to ensure all tags are retrieved even when there are many tags.

        The API returns tags in batches, with a continuation token
        to fetch the next batch until all tags have been retrieved.

        Returns:
            dict: Dictionary mapping tag MAC addresses to their complete data

        Raises:
            Exception: If HTTP requests fail or return unexpected data
        """
        result = {}
        position = 0
        retries_left = 10

        while True:
            path = "get_db"
            if position > 0:
                path += f"?pos={position}"

            try:
                data = await self._ap_request('get', path)

                if not data:
                    self.log.error("Failed to fetch tags from AP")
                    retries_left -= 1
                    if retries_left <= 0:
                        raise Exception(f"Failed to fetch tags after multiple retries")
                    await asyncio.sleep(1)
                    continue

                # Add tags to set
                for tag in data.get("tags", []):
                    if "mac" in tag:
                        result[tag["mac"]] = tag

                # Check for pagination
                if "continu" in data and data["continu"] > 0:
                    position = data["continu"]
                else:
                    break

            except Exception as err:
                self.log.error("Failed to fetch all tags from AP: %s", str(err))
                retries_left -= 1
                if retries_left <= 0:
                    raise
                await asyncio.sleep(1)
                continue

        return result

    async def async_load_all_tags(self) -> None:
        """Load all tags from the AP at startup.

        Fetches the complete list of tags from the AP's database and:

        - Processes each tag to update internal state
        - Counts new and updated tags for logging purposes
        - Saves updated data to persistent storage

        This provides a complete initial state for the integration
        without waiting for individual tag check-ins.

        Raises:
            Exception: If fetching or processing tags fails
        """
        try:
            self.log.info("Loading existing tags from AP...")

            # Track the number of processed tags
            new_tags_count = 0
            updated_tags_count = 0

            # Get all tag data from AP
            all_tags = await self._fetch_all_tags_from_ap()

            # Process each tag using the common helper function
            for tag_mac, tag_data in all_tags.items():
                # Process tag with the initial load flag set
                is_new = await self._process_tag_data(tag_mac, tag_data, is_initial_load=True)

                # Update counters
                if is_new:
                    new_tags_count += 1
                else:
                    updated_tags_count += 1
                    
                # publish initial vars   
                await self.pub_vars(tag_data, is_initial_load=True)

            # Save to persistent storage
            self.save_tags()

            if new_tags_count > 0 or updated_tags_count > 0:
                self.log.info("Loaded %d new tags and updated %d existing tags from AP",
                             new_tags_count, updated_tags_count)

        except Exception as err:
            self.log.error("Failed to load tags from AP: %s", err)
            raise
        
    async def _track_record_count_changes(self, new_record_count: int) -> None:
        """Track changes in record count to detect tag deletions.

        When the AP's record count decreases, it indicates that one or more
        tags have been deleted from the AP. This method detects such changes
        and schedules a verification task to identify and remove deleted tags.

        Args:
            new_record_count: New record count reported by the AP
        """
        if self._last_record_count is not None and new_record_count < self._last_record_count:
            # Record count has decreased, indicating a possible tag deletion
            self.log.info(f"AP record count decreased from {self._last_record_count} to {new_record_count}. Checking for deleted tags...")
            await self._verify_and_cleanup_tags()

        # Update the last known record count
        self._last_record_count = new_record_count
        
    async def _verify_and_cleanup_tags(self) -> None:
        """Verify which tags exist on the AP and clean up deleted ones.

        Checks if any locally known tags have been deleted from the AP
        and removes them from:

        - Internal data structures
        - Persistent storage

        This ensures our state matches the actual AP state
        when tags are removed from the AP directly.

        Raises:
            No exceptions are raised as they are caught and logged internally.
        """
        try:
            # Get current tags from AP
            ap_tags = await self._fetch_all_tags_from_ap()

            # Map tags to mac addresses
            ap_macs = set(ap_tags.keys())

            ap_macs_upper = {mac.upper() for mac in ap_macs}
            known_macs_upper = {mac.upper() for mac in self._known_tags}

            # Find locally known tags that are missing from the AP
            deleted_tags = known_macs_upper - ap_macs_upper

            if deleted_tags:
                self.log.info(f"Detected {len(deleted_tags)} deleted tags from AP: {deleted_tags}")

                # Map back to original case if needed
                for tag_mac in list(self._known_tags):  # Create a copy for safe iteration
                    if tag_mac.upper() in deleted_tags:
                        await self._remove_tag(tag_mac)
                        await self.remove_vars(tag_mac)   # delete from web page
                        
            self.log.info(f'tag number updated to {len(self._known_tags)}')
                        
        except Exception as err:
            self.log.error(f"Error while verifying AP tags: {err}")
        
    async def _remove_tag(self, tag_mac: str) -> None:
        """Remove a tag.

        Args:
            tag_mac: The MAC address of the tag to remove.
        """
        self.log.info(f"Removing tag {tag_mac} as it no longer exists on the AP")

        # Remove from known tags and data
        if tag_mac in self._known_tags:
            self._known_tags.remove(tag_mac)
            self._data.pop(tag_mac, None)
            # Update storage
            self.save_tags()
        
    @staticmethod
    def _get_wakeup_reason_string(reason: int) -> str:
        """Convert numeric wakeup reason code to human-readable string.

        Maps the numeric reasons received from the AP to descriptive strings:

        - 0: "TIMED" (normal timed wakeup)
        - 1: "BOOT" (device boot)
        - 2: "GPIO" (GPIO trigger)
        - 3: "NFC" (NFC scan)
        - 4: "BUTTON1" (button 1 pressed)
        - 5: "BUTTON2" (button 2 pressed)
        - 6: "BUTTON3" (button 3 pressed)
        - 7: "BUTTON4" (button 4 pressed)
        - 8: "BUTTON5" (button 5 pressed)
        - 9: "BUTTON6" (button 6 pressed)
        - 10: "BUTTON7" (button 7 pressed)
        - 11: "BUTTON8" (button 8 pressed)
        - 12: "BUTTON9" (button 9 pressed)
        - 13: "BUTTON10" (button 10 pressed)
        - 252: "FIRSTBOOT" (first boot)
        - 253: "NETWORK_SCAN" (network scan)
        - 254: "WDT_RESET" (watchdog reset)

        Args:
            reason: Numeric wakeup reason code from the tag

        Returns:
            str: Human-readable reason or "UNKNOWN_{code}" if not recognized
        """
        reasons = {
            0: "TIMED",
            1: "BOOT",
            2: "GPIO",
            3: "NFC",
            4: "BUTTON1",
            5: "BUTTON2",
            6: "BUTTON3",
            7: "BUTTON4",
            8: "BUTTON5",
            9: "BUTTON6",
            10: "BUTTON7",
            11: "BUTTON8",
            12: "BUTTON9",
            13: "BUTTON10",
            252: "FIRSTBOOT",
            253: "NETWORK_SCAN",
            254: "WDT_RESET"
        }
        return reasons.get(reason, f"UNKNOWN_{reason}")

    @staticmethod
    def _get_ap_state_string(state: int) -> str:
        """Convert AP state code to human-readable string.

        Maps the numeric state codes received from the AP to descriptive strings:

        - 0: "Offline"
        - 1: "Online"
        - 2: "Flashing"
        - 3: "Waiting for reset"
        - etc.

        Args:
            state: Numeric AP state code

        Returns:
            str: Human-readable state or "Unknown: {code}" if not recognized
        """
        states = {
            0: "Offline",
            1: "Online",
            2: "Flashing",
            3: "Waiting for reset",
            4: "Requires power cycle",
            5: "Failed",
            6: "Coming online",
            7: "No radio"
        }
        return states.get(state, f"Unknown: {state}")

    @staticmethod
    def _get_ap_run_state_string(state: int) -> str:
        """Convert AP run state code to human-readable string.

        Maps the numeric run state codes received from the AP to descriptive strings:

        - 0: "Stopped"
        - 1: "Paused"
        - 2: "Running"
        - 3: "Initializing"

        The run state indicates the operational mode of the AP's tag update system.

        Args:
            state: Numeric AP run state code

        Returns:
            str: Human-readable run state or "Unknown: {state}" if not recognized
        """
        states = {
            0: "Stopped",
            1: "Paused",
            2: "Running",
            3: "Initializing",
        }
        return states.get(state, f"Unknown: {state}")

    @staticmethod
    def _get_content_mode_string(mode: int) -> str:
        """Convert content mode code to human-readable string.

        Maps the numeric content mode codes to descriptive strings indicating
        what type of content the tag is displaying:

        - 0: "Not configured"
        - 1: "Current date"
        - 7: "Image URL"
        - 25: "Home Assistant"
        - etc.

        Args:
            mode: Numeric content mode code

        Returns:
            str: Human-readable content mode or "Unknown: {mode}" if not recognized
        """
        modes = {
            0: "Not configured",
            1: "Current date",
            2: "Count days",
            3: "Count hours",
            4: "Current weather",
            5: "Firmware update",
            7: "Image URL",
            8: "Weather forecast",
            9: "RSS Feed",
            10: "QR Code",
            11: "Google calendar",
            12: "Remote content",
            14: "Set NFC URL",
            15: "Custom LUT",
            16: "Buienradar",
            18: "Tag Config",
            19: "JSON template",
            20: "Display a copy",
            21: "AP Info",
            22: "Static image",
            23: "Image preload",
            24: "External image",
            25: "Home Assistant",
            26: "Timestamp",
            27: "Dayahead prices",


        }
        return modes.get(mode, f"Unknown: {mode}")

    @staticmethod
    def _calculate_runtime_delta(new_data: dict, existing_data: dict) -> int:
        """Calculate a tag's runtime delta between check-ins.

        Determines how much runtime to add based on the difference
        between last_seen timestamps, taking into account:

        - Power cycles (resets runtime counter)
        - Invalid intervals (exceeding max_valid_interval)

        Args:
            new_data: New tag data received from AP
            existing_data: Previously stored tag data

        Returns:
            int: Runtime in seconds to add to the tag's total runtime,
                 or 0 if the interval is invalid or a power cycle occurred
        """
        last_seen_old = existing_data.get("last_seen", 0)
        last_seen_new = new_data.get("lastseen", 0)

        if last_seen_old == 0:
            return 0

        time_diff = last_seen_new - last_seen_old
        max_valid_interval = 600  # 10 minutes - max expected interval between check-ins

        wake_reason = new_data.get("wakeupReason")
        is_power_cycle = wake_reason in [1, 252, 254]  # BOOT, FIRSTBOOT, WDT_RESET

        if is_power_cycle or time_diff > max_valid_interval:
            return 0

        return time_diff
        
    async def pub_vars(self, tag_data, is_initial_load=False):
        '''
        publish data if updated; returns current_tag so callers can reuse it.
        '''
        current_tag = None
        try:
            tag_mac = tag_data.get('mac')
            if tag_mac:
                if tag_data.get('pending', 0) < self._data.get(tag_mac, {}).get('pending', 0) or is_initial_load:
                    current_tag = await self._data[tag_mac].get_curent_data()
                    if current_tag:
                        vars = [v.get('vars') for v in current_tag if 'vars' in v.keys()]
                        if vars:
                            await self.publish(f'{self.get_name(tag_mac)}/vars', vars[0])
        except Exception as e:
            self.log.exception(e)
        return current_tag
        
    async def wait_online(self, timeout=20):
        '''
        wait for AP to be online, or timeout
        '''
        count = 0
        while not self.online:
            self.log.warning(f'AP offline - waiting {count}...')
            if (count:=count+1) >= timeout:
                return False
            await asyncio.sleep(1)
        return True
        
    async def handle_mqtt_msg(self, topic, msg):
        '''
        handle imcoming mqtt messages
        '''
        cmd = topic.split('/')
        if len(cmd) == 4:
            cmd.append('vars')  # if no command make default 'vars'
        mac = self.get_mac(cmd[-2])
        command = cmd[-1]
        if not await self.wait_online():
            self.log.warning(f'aborted {command} for {mac}')
            return
        match command:
            case 'upload':
                await self.upload_data(mac, msg, '22')
            case 'json':
                await self.upload_data(mac, msg, '19')
            case 'vars':
                await self.upload_data(mac, msg, '0')
            case 'reboot':
                if msg == 'ON':
                    await self.reboot_ap()
            case _:
                #variable direct
                if command:
                    await self.upload_data(mac, json.dumps({f'{command}' : msg}), '0')
                else:
                    self.log.warning('No command')
                
    async def upload_data(self, mac: str, data: str, type: str, dither: int = 0, ttl: int = 30,
                           preload_type: int = 0, preload_lut: int = 0, lut: int = 1) -> None:
        """Upload data to tag through AP.
        
        see https://github.com/OpenEPaperLink/OpenEPaperLink/wiki/Json-template
        see https://atc1441.github.io/oepl_json_designer/ for a json template designer

        Sends the data to the AP for display on a specific tag using
        multipart/form-data POST request. Configures display parameters
        such as dithering, TTL, and optional preloading.

        Will retry upload on timeout, with increasing backoff times
        NOTE: Embedded server is very touchy, and will NOT accept chunked encoding.
              this is a problem because aiohttp is buggy and will chunk encode even with chunked=False.

        Args:
            hub: Hub instance with connection details
            mac: MAC ID (eg 410BFFFF92127343) of the target tag
            data: the data to upload, could be json, file name, or image bytes (jpg format or raw)
            type: the contentmode type as a string
            dither: Dithering mode (0=none, 1=Floyd-Steinberg, 2=ordered)
            ttl: Time-to-live in seconds
            preload_type: Type for image preloading (0=disabled)
            preload_lut: Look-up table for preloading
            lut: Display refresh LUT mode (1=full, 3=fast, 2=fast no-reds, 0=no-repeats)
        Raises:
            exception: If upload fails or times out
        """
        mac = mac.upper()
        if mac not in self._known_tags:
            self.log.warning(f'tag: {mac} not found')
            return

        self.log.debug("Preparing upload for %s", mac)
        self.log.debug("Upload parameters: type=%s, dither=%d, ttl=%d, preload_type=%d, preload_lut=%d, lut=%d",
                      type, dither, ttl, preload_type, preload_lut, lut)
                      
        # Convert TTL fom seconds to minutes for the AP
        ttl_minutes = max(1, ttl // 60)
        backoff_delay = INITIAL_BACKOFF # Try up to MAX_RETRIES times to upload the image, retrying on TimeoutError.

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Create a new MultipartEncoder for each attempt
                fields = {
                    'mac': mac,
                    'contentmode': type,
                    'dither': str(dither),
                    'ttl': str(ttl_minutes),
                    'lut': str(lut),
                }
                
                match type:
                    case '22' | '25':
                        if isinstance(data, str):
                            with open(data, 'rb') as f:
                                data = f.read()
                                self.log.debug(f'loaded {len(data)} image bytes')
                        else:
                            self.log.debug(f'received {len(data)} image bytes')
                        fields.update({
                            'image': ('image.jpg', data, 'image/jpeg',)
                        })
                        target = 'imgupload'
                    case '19':
                        data = json.dumps(json.loads(data))                         # validate json data
                        fields.update({
                            'json': data,
                        })
                        target = 'jsonupload'
                    case '0':
                        d = json.loads(data)
                        template = d.pop('template', None)
                        new_tag, vars = await self._data[mac].make_tag(vars=d, template_key=template)
                        await self.upload_data(mac, json.dumps(new_tag), '19')
                        await self.publish(f'{self.get_name(mac)}/vars', vars)
                        return
                    case _:
                        self.log.warning(f'unsupported upload type: {type}')
                        return

                if preload_type > 0:
                    fields.update({
                        'preloadtype': str(preload_type),
                        'preloadlut': str(preload_lut),
                    })

                mp_encoder = MultipartEncoder(fields=fields)

                headers = {
                    'Content-Type': mp_encoder.content_type,
                    'Content-Length': str(mp_encoder.len),
                }
                body = mp_encoder.to_string()
                
                resp = await self._ap_request('post', target, data=body, headers=headers)
                self.log.info(f'uploaded image to {mac}: {resp}')

                if 'timeout' in resp.keys():
                    if attempt < MAX_RETRIES:
                        self.log.warning(
                            "Timeout uploading %s (attempt %d/%d), retrying in %ds…",
                            entity_id, attempt, MAX_RETRIES, backoff_delay
                        )
                        await asyncio.sleep(backoff_delay)
                        backoff_delay *= 2
                        continue
                else:
                    break

            except Exception as err:
                self.log.exception(err)


async def main():
    #----------- Global Variables -----------
    global log
    #-------------- Main --------------

    args = parseargs()
    logging.basicConfig(format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s',
                        force=True,
                        level=logging.DEBUG if args.debug else logging.INFO)
    log = logging.getLogger('Main')

    #------------ Main ------------------

    log.info("*******************")
    log.info("* Program Started *")
    log.info("*******************")
    
    log.info("OpenEPaper.py Version: %s" % __version__)
    log.info("Python Version: %s" % sys.version.replace('\n',''))
    log.debug("DEBUG mode on")
    
    folder = Path(args.folder)
    if not folder.is_dir():
        log.warning(f'folder {folder} does not exist - web server will not be started')
        folder = None
    
    e = EPaper(args.ap,
               folder     = folder,
               server     = args.server,
               port       = args.port,
               login      = args.login,
               password   = args.password,
               topic      = args.topic)
    
    await e.run()
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("System exit Received - Exiting program")
    logging.info('Program Exited')