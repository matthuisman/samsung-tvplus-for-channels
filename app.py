#!/usr/bin/python3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qsl, quote, unquote
import requests
import gzip
from io import BytesIO

PORT = 80
REGION_ALL = 'all'
CHUNKSIZE = int(os.getenv('CHUNK_SIZE', 64 * 1024))

PLAYLIST_URL = 'playlist.m3u8'
EPG_URL = 'epg.xml'
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
        # Serve the favicon.ico file
        if self.path == '/favicon.ico':
            self._serve_favicon()
            return

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

    def _playlist(self):
        all_channels = requests.get(APP_URL).json()['regions']

        # Retrieve filters from URL or fallback to environment variables
        regions = [region.strip().lower() for region in (self._params.get('regions') or os.getenv('REGIONS', REGION_ALL)).split(',')]
        regions = [region for region in all_channels.keys() if region.lower() in regions or REGION_ALL in regions]
        groups = [unquote(group).lower() for group in (self._params.get('groups') or os.getenv('GROUPS', '')).split(',')]
        groups = [group for group in groups if group]

        start_chno = int(self._params['start_chno']) if 'start_chno' in self._params else None
        sort = self._params.get('sort', 'chno')
        include = [x for x in self._params.get('include', '').split(',') if x]
        exclude = [x for x in self._params.get('exclude', '').split(',') if x]

        self.send_response(200)
        self.send_header('content-type', 'vnd.apple.mpegurl')
        self.end_headers()

        channels = {}
        print(f"Including channels from regions: {regions}")
        for region in regions:
            channels.update(all_channels[region].get('channels', {}))

        self.wfile.write(b'#EXTM3U\n')
        for key in sorted(channels.keys(), key=lambda x: channels[x]['chno'] if sort == 'chno' else channels[x]['name'].strip().lower()):
            channel = channels[key]
            logo = channel['logo']
            group = channel['group']
            name = channel['name']
            url = channel['url']
            channel_id = f'samsung-{key}'

            # Skip channels with no URL or channels that require a license
            if not url or channel.get('license_url'):
                continue

            # Apply include/exclude filters
            if (include and channel_id not in include) or (exclude and channel_id in exclude):
                print(f"Skipping {channel_id} due to include / exclude")
                continue

            # Apply group filter
            if groups and group.lower() not in groups:
                print(f"Skipping {channel_id} due to group filter")
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
        # Download the .gz EPG file
        resp = requests.get(f'https://i.mjh.nz/SamsungTVPlus/{REGION_ALL}.xml.gz')

        if resp.status_code != 200:
            self._error("Failed to retrieve EPG file.")
            return

        # Decompress the .gz content
        with gzip.GzipFile(fileobj=BytesIO(resp.content)) as gz:
            xml_content = gz.read()

        # Serve the decompressed XML content
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(xml_content)

    def _proxy(self, url, content_type=None):
        resp = requests.get(url)
        self.send_response(resp.status_code)
        self.send_header('content-type', content_type or resp.headers.get('content-type'))
        self.end_headers()
        for chunk in resp.iter_content(CHUNKSIZE):
            self.wfile.write(chunk)

    def _status(self):
        all_channels = requests.get(APP_URL).json()['regions']

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
                <h1>Samsung TV Plus for Channels</h1>
                <p>Playlist URL: <b><a href="http://{host}/{PLAYLIST_URL}">http://{host}/{PLAYLIST_URL}</a></b></p>
                <p>EPG URL (Set to refresh every 1 hour): <b><a href="http://{host}/{EPG_URL}">http://{host}/{EPG_URL}</a></b></p>
                <h2>Available regions &amp; groups</h2>
        '''.encode('utf8'))

        # Display regions and their group titles with links
        for region, region_data in all_channels.items():
            encoded_region = quote(region)
            self.wfile.write(f'<h3><a href="http://{host}/{PLAYLIST_URL}?regions={encoded_region}">{region_data["name"]}</a> ({region})</h3><ul>'.encode('utf8'))

            group_names = set(channel.get('group', None) for channel in region_data.get('channels', {}).values())
            for group in sorted(name for name in group_names if name):
                encoded_group = quote(group)
                self.wfile.write(f'<li><a href="http://{host}/{PLAYLIST_URL}?regions={encoded_region}&groups={encoded_group}">{group}</a></li>'.encode('utf8'))
            self.wfile.write(b'</ul>')

        self.wfile.write(b'</body></html>')


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


def run():
    server = ThreadingSimpleServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()


if __name__ == '__main__':
    run()
