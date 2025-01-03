#!/usr/bin/python3
import os
import json
import gzip
import argparse
from base64 import b64encode
from io import BytesIO
from tempfile import gettempdir
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qsl, quote, unquote

import requests
from cachelib import SimpleCache


REGION_ALL = 'all'
PLAYLIST_PATH = 'playlist.m3u8'
EPG_PATH = 'epg.xml'
CLEAR_CACHE_PATH = 'clear_cache'
STATUS_PATH = ''
APP_URL = 'https://i.mjh.nz/SamsungTVPlus/.channels.json.gz'
EPG_URL = 'https://i.mjh.nz/SamsungTVPlus/{region}.xml.gz'
PLAYBACK_URL = 'https://jmp2.uk/sam-{id}.m3u8'
DELIMITER = '|'
TIMEOUT = (5,20) #connect,read
CACHE_TIME = os.getenv("CACHE_TIME", 300) # default of 5mins
CHUNKSIZE = 1024

CACHE_DIR = os.path.join(gettempdir(), 'samsung-tvplus-for-channels')
os.makedirs(CACHE_DIR, exist_ok=True)
print(f"Cache dir: {CACHE_DIR}")
cache = SimpleCache()


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
        # Serve the favicon.ico file
        if self.path == '/favicon.ico':
            self._serve_favicon()
            return

        routes = {
            PLAYLIST_PATH: self._playlist,
            EPG_PATH: self._epg,
            STATUS_PATH: self._status,
            CLEAR_CACHE_PATH: self._clear_cache,
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

    def _clear_cache(self):
        cache.clear()
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'Cache cleared')

    def _serve_favicon(self):
        # Serve the favicon file as an ICO file
        try:
            with open('favicon.ico', 'rb') as f:
                self.send_response(200)
                self.send_header('Content-Type', 'image/x-icon')
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def _app_data(self):
        cache_path = cache.get(APP_URL)
        if cache_path and os.path.exists(cache_path):
            self.log_message(f"Cache hit: {APP_URL}")
            with open(cache_path, 'r') as f:
                return json.load(f)

        cache_path = os.path.join(CACHE_DIR, b64encode(APP_URL.encode()).decode())
        self.log_message(f"Downloading {APP_URL}...")
        resp = requests.get(APP_URL, stream=True, timeout=TIMEOUT)
        resp.raise_for_status()
        json_text = gzip.GzipFile(fileobj=BytesIO(resp.content)).read()
        data = json.loads(json_text)['regions']
        with open(cache_path, 'w') as f:
            json.dump(data, f)
        cache.set(APP_URL, cache_path, timeout=CACHE_TIME)
        return data

    def _playlist(self):
        all_channels = self._app_data()

        # Retrieve filters from URL or fallback to environment variables
        regions = [region.strip().lower() for region in (self._params.get('regions') or os.getenv('REGIONS', REGION_ALL)).split(DELIMITER)]
        regions = [region for region in all_channels.keys() if region.lower() in regions or REGION_ALL in regions]
        groups = [unquote(group).lower() for group in (self._params.get('groups') or os.getenv('GROUPS', '')).split(DELIMITER)]
        groups = [group for group in groups if group]

        start_chno = int(self._params['start_chno']) if 'start_chno' in self._params else None
        sort = self._params.get('sort', 'chno')
        include = [x for x in self._params.get('include', '').split(DELIMITER) if x]
        exclude = [x for x in self._params.get('exclude', '').split(DELIMITER) if x]

        self.send_response(200)
        self.send_header('content-type', 'vnd.apple.mpegurl')
        self.end_headers()

        channels = {}
        self.log_message(f"Including channels from regions: {regions} in groups: {groups}")
        for region in regions:
            channels.update(all_channels[region].get('channels', {}))

        self.wfile.write(b'#EXTM3U\n')
        for key in sorted(channels.keys(), key=lambda x: channels[x]['chno'] if sort == 'chno' else channels[x]['name'].strip().lower()):
            channel = channels[key]
            logo = channel['logo']
            group = channel['group']
            name = channel['name']
            url = PLAYBACK_URL.format(id=key)
            channel_id = f'samsung-{key}'

            # Skip channels that require a license
            if channel.get('license_url'):
                continue

            # Apply include/exclude filters
            if (include and channel_id not in include) or (exclude and channel_id in exclude):
                continue

            # Apply group filter
            if groups and group.lower() not in groups:
                continue

            chno = ''
            if start_chno is not None:
                if start_chno > 0:
                    chno = f' tvg-chno="{start_chno}"'
                    start_chno += 1
            elif channel.get('chno') is not None:
                chno = ' tvg-chno="{}"'.format(channel['chno'])

            # Write channel information
            self.wfile.write(f'#EXTINF:-1 channel-id="{channel_id}" tvg-id="{key}" tvg-logo="{logo}" group-title="{group}"{chno},{name}\n{url}\n'.encode('utf8'))

    def _epg(self):
        regions = (self._params.get('regions') or os.getenv('REGIONS', REGION_ALL)).split(DELIMITER)
        region = regions[0] if len(regions) == 1 else REGION_ALL
        url = EPG_URL.format(region=region)

        cache_path = cache.get(url)
        if cache_path and os.path.exists(cache_path):
            self.log_message(f"Cache hit: {url}...")
            self.send_response(200)
            self.send_header('Content-Type', 'application/xml')
            self.end_headers()
            with open(cache_path, 'rb') as f:
                chunk = f.read(CHUNKSIZE)
                while chunk:
                    self.wfile.write(chunk)
                    chunk = f.read(CHUNKSIZE)
            return

        self.log_message(f"Downloading {url}...")
        cache_path = os.path.join(CACHE_DIR, b64encode(url.encode()).decode())
        # Download the .gz EPG file
        with open(cache_path, 'wb') as cache_f:
            with requests.get(url, stream=True, timeout=TIMEOUT) as resp:
                resp.raise_for_status()

                self.send_response(200)
                self.send_header('Content-Type', 'application/xml')
                self.end_headers()

                # Decompress the .gz content
                with gzip.GzipFile(fileobj=BytesIO(resp.content)) as gz:
                    chunk = gz.read(CHUNKSIZE)
                    while chunk:
                        cache_f.write(chunk)
                        self.wfile.write(chunk)
                        chunk = gz.read(CHUNKSIZE)
        cache.set(url, cache_path, timeout=CACHE_TIME)

    def _status(self):
        # Generate HTML content with the favicon link
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        host = self.headers.get('Host')
        self.wfile.write(f'''
            <html>
            <head>
                <title>Samsung TV Plus for Channels</title>
                <link rel="icon" href="/favicon.ico" type="image/x-icon">
            </head>
            <body>
                <h1>Regions &amp; Groups</h1>
                <h2>All</h2>
                Playlist URL: <b><a href="http://{host}/{PLAYLIST_PATH}">http://{host}/{PLAYLIST_PATH}</a></b><br>
                EPG URL (Set to refresh once per hour): <b><a href="http://{host}/{EPG_PATH}">http://{host}/{EPG_PATH}</a></b>
        '''.encode('utf8'))

        # Display regions and their group titles with links
        for region, region_data in self._app_data().items():
            encoded_region = quote(region)
            self.wfile.write(f'''<h2>{region_data["name"]}</h2>
                             Playlist URL: <b><a href="http://{host}/{PLAYLIST_PATH}?regions={encoded_region}">http://{host}/{PLAYLIST_PATH}?regions={encoded_region}</a></b><br>
                             EPG URL (Set to refresh once per hour): <b><a href="http://{host}/{EPG_PATH}?regions={encoded_region}">http://{host}/{EPG_PATH}?regions={encoded_region}</a></b><br><ul>'''.encode('utf8'))

            group_names = set(channel.get('group', None) for channel in region_data.get('channels', {}).values())
            for group in sorted(name for name in group_names if name):
                encoded_group = quote(group)
                self.wfile.write(f'<li><a href="http://{host}/{PLAYLIST_PATH}?regions={encoded_region}&groups={encoded_group}">{group}</a></li>'.encode('utf8'))
            self.wfile.write(b'</ul>')

        self.wfile.write(b'</body></html>')


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


def run():
    if os.getenv('IS_DOCKER'):
        PORT = 80
    else:
        parser = argparse.ArgumentParser(description="Samsung TV Plus for Channels")
        parser.add_argument("-port", "--PORT", default=80, help="Port number for server to use (optional)")
        args = parser.parse_args()
        PORT = args.PORT

    print(f"Starting server on port {PORT}")
    server = ThreadingSimpleServer(('0.0.0.0', int(PORT)), Handler)
    server.serve_forever()


if __name__ == '__main__':
    run()
