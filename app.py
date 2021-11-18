#!/usr/bin/python3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from urllib.parse import urlparse, parse_qsl

import requests

PORT = 80
REGION = os.getenv('REGION', 'us').strip().lower()
CHUNKSIZE = int(os.getenv('CHUNK_SIZE', 64 * 1024))

PLAYLIST_URL = 'playlist.m3u'
EPG_URL = 'epg.xml'
STATUS_URL = ''
APP_URL = 'https://i.mjh.nz/SamsungTVPlus/app.json'

class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self._params = {}
        super().__init__(*args, **kwargs)

    def _error(self, message):
        self.send_response(500)
        self.end_headers()
        self.wfile.write(f'Error: {message}'.encode('utf8'))
        raise

    def do_GET(self):
        routes = {
            PLAYLIST_URL: self._playlist,
            EPG_URL: self._epg,
            STATUS_URL: self._status,
        }

        parsed = urlparse(self.path)
        func = parsed.path.lstrip('/')
        self._params = dict(parse_qsl(parsed.query, keep_blank_values=True))

        if func not in routes:
            self.send_response(404)
            self.end_headers()
            return

        try:
            routes[func]()
        except Exception as e:
            self._error(e)

    def _playlist(self):
        regions = requests.get(APP_URL).json()['regions']

        channels = {}
        if REGION == 'all':
            for key, region in regions.items():
                channels.update(region.get('channels', {}))
        else:
            channels = regions[REGION].get('channels', {})

        start_chno = int(self._params['start_chno']) if 'start_chno' in self._params else None
        sort = self._params.get('sort', 'chno')
        include = [x for x in self._params.get('include', '').split(',') if x]
        exclude = [x for x in self._params.get('exclude', '').split(',') if x]

        self.wfile.write(b'#EXTM3U\n')
        for key in sorted(channels.keys(), key=lambda x: channels[x]['chno'] if sort == 'chno' else channels[x]['name'].strip().lower()):
            if (include and key not in include) or (exclude and key in exclude):
                continue

            channel = channels[key]
            logo = channel['logo']
            group = channel['group']
            name = channel['name']
            url = channel['url']

            chno = ''
            if start_chno is not None:
                if start_chno > 0:
                    chno = f' tvg-chno="{start_chno}"'
                    start_chno += 1
            elif channel.get('chno') is not None:
                chno = ' tvg-chno="{}"'.format(channel['chno'])

            self.wfile.write(f'#EXTINF:-1 tvg-id="{key}" channel-id="samsung-{key}" tvg-logo="{logo}" group-title="{group}"{chno},{name}\n{url}\n'.encode('utf8'))

    def _epg(self):
        self._proxy(f'https://i.mjh.nz/SamsungTVPlus/{REGION}.xml')

    def _proxy(self, url):
        resp = requests.get(url)
        self.send_response(resp.status_code)
        self.send_header('content-type', resp.headers.get('content-type'))
        self.end_headers()
        if resp.ok:
            for chunk in resp.iter_content(CHUNKSIZE):
                self.wfile.write(chunk)
        else:
            self.wfile.write(f'{url} returned error {resp.status_code}\nCheck your REGION is correct'.encode('utf8'))

    def _status(self):
        self.send_response(200)
        self.end_headers()
        host = self.headers.get('Host')
        self.wfile.write(f'Playlist URL: http://{host}/{PLAYLIST_URL}\nEPG URL: http://{host}/{EPG_URL}'.encode('utf8'))

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

def run():
    server = ThreadingSimpleServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()

if __name__ == '__main__':
    run()
