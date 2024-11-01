#!/usr/bin/python3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qsl

import requests


PORT = 80
REGION_ALL = 'all'
CHUNKSIZE = int(os.getenv('CHUNK_SIZE', 64 * 1024))

PLAYLIST_URL = 'playlist.m3u8'
EPG_URL = 'epg.xml.gz'
STATUS_URL = ''
APP_URL = 'https://i.mjh.nz/SamsungTVPlus/.app.json'


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
        func = parsed.path.split('/')[1]
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
        all_channels = requests.get(APP_URL).json()['regions']

        regions = [region.strip().lower() for region in (self._params.get('regions') or os.getenv('REGIONS', 'us')).split(',')]
        regions = [region for region in all_channels.keys() if region in regions or REGION_ALL in regions]

        channels = {}
        print(f"Including channels from regions: {regions}")
        for region in regions:
            channels.update(all_channels[region].get('channels', {}))

        start_chno = int(self._params['start_chno']) if 'start_chno' in self._params else None
        sort = self._params.get('sort', 'chno')
        include = [x for x in self._params.get('include', '').split(',') if x]
        exclude = [x for x in self._params.get('exclude', '').split(',') if x]

        self.send_response(200)
        self.send_header('content-type', 'vnd.apple.mpegurl')
        self.end_headers()

        self.wfile.write(b'#EXTM3U\n')
        for key in sorted(channels.keys(), key=lambda x: channels[x]['chno'] if sort == 'chno' else channels[x]['name'].strip().lower()):
            channel = channels[key]
            logo = channel['logo']
            group = channel['group']
            name = channel['name']
            url = channel['url']
            channel_id = f'samsung-{key}'

            # skip no urls or widevine channels
            if not url or channel.get('license_url'):
                continue

            if (include and channel_id not in include) or (exclude and channel_id in exclude):
                print(f"Skipping {channel_id} due to include / exclude")
                continue

            chno = ''
            if start_chno is not None:
                if start_chno > 0:
                    chno = f' tvg-chno="{start_chno}"'
                    start_chno += 1
            elif channel.get('chno') is not None:
                chno = ' tvg-chno="{}"'.format(channel['chno'])

            self.wfile.write(f'#EXTINF:-1 channel-id="{channel_id}" tvg-id="{key}" tvg-logo="{logo}" group-title="{group}"{chno},{name}\n{url}\n'.encode('utf8'))

    def _epg(self):
        self._proxy(f'https://i.mjh.nz/SamsungTVPlus/{REGION_ALL}.xml.gz')

    def _proxy(self, url):
        resp = requests.get(url)
        self.send_response(resp.status_code)
        self.send_header('content-type', 'application/gzip')
        self.end_headers()
        for chunk in resp.iter_content(CHUNKSIZE):
            self.wfile.write(chunk)

    def _status(self):
        all_channels = requests.get(APP_URL).json()['regions']
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        host = self.headers.get('Host')
        self.wfile.write(f'Playlist URL: <a href="http://{host}/{PLAYLIST_URL}">http://{host}/{PLAYLIST_URL}</a><br>EPG URL (Set to Refresh Every 1 Hour): <a href="http://{host}/{EPG_URL}">http://{host}/{EPG_URL}</a><br><br>Available Regions: {",".join(all_channels.keys())}'.encode('utf8'))


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


def run():
    server = ThreadingSimpleServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()


if __name__ == '__main__':
    run()
