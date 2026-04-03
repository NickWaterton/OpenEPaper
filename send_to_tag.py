#!/usr/bin/env python3

"""
OpenEPaper sent variables to tag using MQTT topic

This is intended for an MQTT interfact to an OpenEPaper ESL via an AP
N Waterton 24/2/2026 V 1.0.0 : Initial Release
"""

__version__ = '1.0.0'

import sys, json
import logging
import argparse
import asyncio

import aiomqtt

logging.basicConfig(level=logging.INFO)

# manual command
# mosquitto_pub -h 192.168.100.16 -t "/openepaper/command/AMS1/vars" -m '{"pct": "100", "color": "white", "fil": "TEST", "type": "None", "name": "Test", "in_use_col_bg" : "white", "fil_txt_col": "black"}'

def parseargs():
    # Add command line argument parsing
    parser = argparse.ArgumentParser(description='OpenEPaper Send to ESL Tag Version: {}'.format(__version__))
    parser.add_argument('name', action="store", type=str, default=None, help='Name of the tag to send to as given in top left corner (default: %(default)s))')
    parser.add_argument('-c','--color', action="store", type=str, default=None, help='Colour to set (default: %(default)s))')
    parser.add_argument('-ty','--type', action="store", type=str, default=None, help='Type as shown in top right to set (default: %(default)s))')
    parser.add_argument('-f','--fil', action="store", type=str, default=None, help='Filament to set (use "" if spaces in filament name) (default: %(default)s))')
    parser.add_argument('-P','--pct', action="store", type=str, default=None, help='Pct to set 0-100 (default: %(default)s))')
    parser.add_argument('-iu','--in_use_bg', action="store", type=str, default='white', choices=['white','black','red'], help='In Use Background colour to set (default: %(default)s))')
    parser.add_argument('-ft','--fil_text', action="store", type=str, default='black', choices=['white','black','red'], help='Filament Text colour to set (default: %(default)s))')
    parser.add_argument('-s','--server', action="store", type=str, default="192.168.100.16", help='MQTT Server address (default: %(default)s))')
    parser.add_argument('-p','--port', action="store", type=int, default=1883, help='MQTT server port (default: %(default)s))')
    parser.add_argument('-l','--login', action="store", type=str, default="", help='optional MQTT server login (default: %(default)s))')
    parser.add_argument('-pw','--password', action="store", type=str, default="", help='optional MQTT server password (default: %(default)s))')
    parser.add_argument('-t','--topic', action="store", type=str, default="/openepaper/command", help='topic to publish OpenEPaper command to (default: %(default)s))')
    parser.add_argument('-D','--debug', action='store_true', default=False, help='Debug mode (default: %(default)s))')
    return parser.parse_args()
    
class SEND_TO_TAG:
    
    def __init__(self, name,
                       pct,
                       color,
                       fil,
                       type,
                       in_use_col_bg,
                       fil_txt_col,
                       server="192.168.100.16",
                       port=1883,
                       login="",
                       password="",
                       topic=None):
        self.log = logging.getLogger('Main.'+__class__.__name__)
        self.debug = self.log.getEffectiveLevel() <= logging.DEBUG
        self.name = name
        self.pct = pct
        self.color = color
        self.fil = fil
        self.type = type
        self.in_use_col_bg = in_use_col_bg
        self.fil_txt_col = fil_txt_col
        self.server = server
        self.port = port
        self.login = login
        self.password = password
        self.topic = topic
        
    def make_message(self):
        vars = {"pct": self.pct, "color": self.color, "fil": self.fil, "type": self.type, "in_use_col_bg": self.in_use_col_bg, "fil_txt_col": self.fil_txt_col}
        vars = {k:v for k,v in vars.items() if v is not None}
        return json.dumps(vars)

    async def send(self):
        '''
        Just publishes message and ends
        '''
        client = aiomqtt.Client(self.server, port=self.port, username=self.login, password=self.password)
        self.log.info('connecting to MQTT broker: {}:{}'.format(self.server, self.port))
        async with client as cl:
            msg = self.make_message()
            topic = f'{self.topic}/{self.name}/vars'
            if msg:
                await cl.publish(topic, msg)
                self.log.info(f'published to {topic}: {msg}')
    
async def main():
    #----------- Global Variables -----------
    global log
    #-------------- Main --------------

    args = parseargs()
    logging.basicConfig(format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s',
                        force=True,
                        level=logging.DEBUG if args.debug else logging.INFO)
    log = logging.getLogger('Main')
    logging.getLogger(__package__).setLevel(log.getEffectiveLevel())

    #------------ Main ------------------
    log.info("send_to_tag.py Version: %s" % __version__)
    log.info("Python Version: %s" % sys.version.replace('\n',''))
    log.debug("DEBUG mode on")
    
    client = SEND_TO_TAG( name          = args.name,
                          pct           = args.pct,
                          color         = args.color,
                          fil           = args.fil,
                          type          = args.type,
                          in_use_col_bg = args.in_use_bg,
                          fil_txt_col   = args.fil_text,
                          server        = args.server,
                          port          = args.port,
                          login         = args.login,
                          password      = args.password,
                          topic         = args.topic)
                          
    await client.send()

if __name__ == "__main__":
    asyncio.run(main())