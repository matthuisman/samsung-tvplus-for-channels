#!/usr/bin/python3
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qsl, quote, unquote
import requests
import gzip
from io import BytesIO
from time import time

PORT = 80
REGION_ALL = 'all'
CHUNKSIZE = int(os.getenv('CHUNK_SIZE', 64 * 1024))

PLAYLIST_PATH = 'playlist.m3u8'
EPG_PATH = 'epg.xml'
STATUS_PATH = ''
APP_URL = 'https://i.mjh.nz/SamsungTVPlus/.channels.json'
EPG_URL = f'https://i.mjh.nz/SamsungTVPlus/{REGION_ALL}.xml.gz'
PLAYBACK_URL = 'https://jmp2.uk/sam-{id}.m3u8'

CHANNEL_CACHE_EXPIRY = 5 * 60  # 5 minutes
EPG_CACHE_EXPIRY = 60 * 60 # 60 minutes


class Handler(BaseHTTPRequestHandler):

    # Class-level cache for APP_URL data
    cached_data = None
    cache_timestamp = None
    epg_cache_data = None
    epg_cache_timestamp = None
    channel_cache_lock = threading.Lock()  # Lock for synchronizing channel data cache
    epg_cache_lock = threading.Lock()  # Lock for synchronizing EPG data cache

    def __init__(self, *args, **kwargs):
        self._params = {}
        super().__init__(*args, **kwargs)

    @classmethod
    def get_cached_channel_data(cls):
        # Retrieve cached channel data if it's less than {CHANNEL_CACHE_EXPIRY} seconds old, otherwise fetch new data.
        with cls.channel_cache_lock:
            current_time = time()
            if cls.cached_data and (current_time - cls.cache_timestamp) < CHANNEL_CACHE_EXPIRY:
                print(f"Using Cached version of ${APP_URL}")
                return cls.cached_data
            else:
                print(f"Fetching new data from {APP_URL}")
                try:
                    response = requests.get(APP_URL)
                    response.raise_for_status()  # Ensure we received a successful response

                    # Validate JSON content, do not store if invalid.
                    try:
                        json_data = response.json()  # Attempt to decode JSON
                        if 'regions' in json_data:
                            cls.cached_data = json_data['regions']
                            cls.cache_timestamp = current_time
                            print("Successfully updated channel cache.")
                            return cls.cached_data
                        else:
                            print(f"Invalid JSON format: 'regions' key not found in response.")
                            return None
                    except ValueError as e:
                        print(f"JSON decoding failed: {e}")
                        return None

                except requests.RequestException as e:
                    print(f"Error fetching data from {APP_URL}: {e}")
                    return None

    @classmethod
    def get_cached_epg_data(cls):
        # Retrieve cached EPG data if it's less than {EPG_CACHE_EXPIRY} seconds old, otherwise fetch and decompress."""
        with cls.epg_cache_lock:
            current_time = time()
            if cls.epg_cache_data and (current_time - cls.epg_cache_timestamp) < EPG_CACHE_EXPIRY:
                print("Using cached EPG data.")
                return cls.epg_cache_data
            else:
                print("Fetching new EPG data.")
                try:
                    response = requests.get(EPG_URL, stream=True)
                    response.raise_for_status()

                    with gzip.GzipFile(fileobj=BytesIO(response.content)) as gz:
                        cls.epg_cache_data = gz.read()  # Store the decompressed XML content
                        cls.epg_cache_timestamp = current_time
                        print("Successfully updated EPG cache.")
                        return cls.epg_cache_data

                except requests.RequestException as e:
                    print(f"Error fetching EPG data: {e}")
                    return None

    def _error(self, message):
        self.send_response(500)
        self.end_headers()
        self.wfile.write(f'Error: {message}'.encode('utf8'))
        raise

    def do_GET(self):

        # Log the incoming request with route and parameters
        parsed = urlparse(self.path)
        route = parsed.path
        self._params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        print(f"Received request on {route} with params: {self._params}")

        # Serve the favicon.ico file
        if self.path == '/favicon.ico':
            self._serve_favicon()
            return

        routes = {
            PLAYLIST_PATH: self._playlist,
            EPG_PATH: self._epg,
            STATUS_PATH: self._status,
        }

        parsed = urlparse(self.path)
        func = parsed.path.split('/')[1]
        self._params = dict(parse_qsl(parsed.query, keep_blank_values=True))

        if func not in routes:
            self.send_response(404)
            self.end_headers()
            print(f"404 Not Found: {route}")
            return

        try:
            routes[func]()
        except Exception as e:
            self._error(e)
            print(f"Error handling request on {route}: {e}")

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
        try:
            all_channels = self.get_cached_channel_data()
            if all_channels is None:
                self._error("Failed to retrieve data from server.")
                return

            # Retrieve filters from URL or fallback to environment variables
            regions = [region.strip().lower() for region in
                       (self._params.get('regions') or os.getenv('REGIONS', REGION_ALL)).split(',')]
            regions = [region for region in all_channels.keys() if region.lower() in regions or REGION_ALL in regions]
            groups = [unquote(group).lower() for group in
                      (self._params.get('groups') or os.getenv('GROUPS', '')).split(',')]
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

            try:
                self.wfile.write(b'#EXTM3U\n')
                for key in sorted(channels.keys(), key=lambda x: channels[x]['chno'] if sort == 'chno' else channels[x]['name'].strip().lower()):
                    # noisy output, but might be good for debugging.
                    # print(f"processing channel id ${key}")
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
                    try:
                        self.wfile.write(
                            f'#EXTINF:-1 channel-id="{channel_id}" tvg-id="{key}" tvg-logo="{logo}" group-title="{group}"{chno},{name}\n{url}\n'.encode('utf8'))
                    except BrokenPipeError:
                        print(f"Client disconnected while sending channel data for {channel_id}")
                        break
            except BrokenPipeError:
                print("Client disconnected during playlist generation")

        except requests.RequestException as e:
            print(f"Error fetching data from {APP_URL}: {e}")
            self._error("Could not retrieve data from remote server.")

    def _epg(self):
        epg_data = self.get_cached_epg_data()
        if epg_data is None:
            self._error("Failed to retrieve EPG file.")
            return

        # Serve the cached EPG data
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(epg_data)

    def _proxy(self, url, content_type=None):
        resp = requests.get(url)
        self.send_response(resp.status_code)
        self.send_header('content-type', content_type or resp.headers.get('content-type'))
        self.end_headers()
        for chunk in resp.iter_content(CHUNKSIZE):
            self.wfile.write(chunk)

    def _status(self):
        all_channels = self.get_cached_channel_data()
        if all_channels is None:
            self._error("Failed to retrieve data from server.")
            return

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
            <p>Playlist URL: <b><a href="http://{host}/{PLAYLIST_PATH}">http://{host}/{PLAYLIST_PATH}</a></b></p>
            <p>EPG URL (Set to refresh every 1 hour): <b><a href="http://{host}/{EPG_PATH}">http://{host}/{EPG_PATH}</a></b></p>
            <h2>Available regions &amp; groups</h2>
    '''.encode('utf8'))

        # Display regions and their group titles with links
        for region, region_data in all_channels.items():
            encoded_region = quote(region)
            self.wfile.write(f'<h3><a href="http://{host}/{PLAYLIST_PATH}?regions={encoded_region}">{region_data["name"]}</a> ({region})</h3><ul>'.encode('utf8'))

            group_names = set(channel.get('group', None) for channel in region_data.get('channels', {}).values())
            for group in sorted(name for name in group_names if name):
                encoded_group = quote(group)
                self.wfile.write(f'<li><a href="http://{host}/{PLAYLIST_PATH}?regions={encoded_region}&groups={encoded_group}">{group}</a></li>'.encode('utf8'))
            self.wfile.write(b'</ul>')

        self.wfile.write(b'</body></html>')


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


def run():
    server = ThreadingSimpleServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
    print(f"Server listening on port {PORT}")


if __name__ == '__main__':
    run()
