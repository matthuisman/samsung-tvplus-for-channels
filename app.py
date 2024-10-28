#!/usr/bin/python3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qsl, quote, unquote
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
        response = requests.get(APP_URL)
        all_channels_data = response.json()
        
        if 'regions' not in all_channels_data:
            self._error("Unable to retrieve regions data.")
            return
            
        all_channels = all_channels_data['regions']

        # Normalize region names in the data for case-insensitive matching
        all_channels = {region.lower(): data for region, data in all_channels.items()}

        # Retrieve region and group filters
        region_filter = self._params.get('region', REGION_ALL).strip().lower()
        if region_filter == REGION_ALL:
            regions = list(all_channels.keys())
        elif region_filter in all_channels:
            regions = [region_filter]
        else:
            self._error(f"Region '{region_filter}' not found.")
            return

        group_filter = self._params.get('group')
        if group_filter:
            group_filter = unquote(group_filter).lower()

        channels = {}
        print(f"Including channels from regions: {regions}")
        for region in regions:
            if region in all_channels:
                channels.update(all_channels[region].get('channels', {}))
            else:
                print(f"Warning: Region '{region}' not found in data")

        # Retrieve additional filter parameters
        start_chno = int(self._params['start_chno']) if 'start_chno' in self._params else None
        sort = self._params.get('sort', 'chno')
        include = [x for x in self._params.get('include', '').split(',') if x]
        exclude = [x for x in self._params.get('exclude', '').split(',') if x]

        self.send_response(200)
        self.end_headers()

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
            if group_filter and group_filter != group.lower():
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
        self._proxy(f'https://i.mjh.nz/SamsungTVPlus/{REGION_ALL}.xml.gz')

    def _proxy(self, url):
        resp = requests.get(url)
        self.send_response(resp.status_code)
        self.send_header('content-type', resp.headers.get('content-type'))
        self.end_headers()
        for chunk in resp.iter_content(CHUNKSIZE):
            self.wfile.write(chunk)

    def _status(self):
        # Fetch all channels data
        response = requests.get(APP_URL)
        all_channels_data = response.json()
        
        if 'regions' not in all_channels_data:
            self._error("Unable to retrieve regions data.")
            return
            
        all_channels = all_channels_data['regions']
        
        # Normalize region names in the data for consistency
        all_channels = {region.lower(): data for region, data in all_channels.items()}
        
        # Generate HTML content with the favicon link
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        host = self.headers.get('Host')
        self.wfile.write(f'''
            <html>
            <head>
                <title>Server Status - Samung TV Plus for Channels</title>
                <link rel="icon" href="/favicon.ico" type="image/x-icon">
            </head>
            <body>
                <h1>Server Status</h1>
                <p>Playlist URL: <a href="http://{host}/{PLAYLIST_URL}">http://{host}/{PLAYLIST_URL}</a></p>
                <p>EPG URL (Set to refresh every 1 hour): <a href="http://{host}/{EPG_URL}">http://{host}/{EPG_URL}</a></p>
                <p>Available regions:</p>
                <ul>
        '''.encode('utf8'))

        # Display each region as a clickable link
        for region_name in all_channels.keys():
            encoded_region = quote(region_name)
            self.wfile.write(f'<li><a href="http://{host}/{PLAYLIST_URL}?region={encoded_region}">{region_name}</a></li>'.encode('utf8'))

        self.wfile.write(b'</ul><p>Available group titles by region:</p>')

        # Display regions and their group titles with links
        for region_name, region_data in all_channels.items():
            self.wfile.write(f'<p>Region: {region_name}</p><ul>'.encode('utf8'))
            group_names = set(channel.get('group', 'Unknown') for channel in region_data.get('channels', {}).values())
            
            for group in sorted(group_names):
                encoded_region = quote(region_name)
                encoded_group = quote(group)
                self.wfile.write(f'<li><a href="http://{host}/{PLAYLIST_URL}?region={encoded_region}&group={encoded_group}">{group}</a></li>'.encode('utf8'))
            
            self.wfile.write(b'</ul>')

        # Close the HTML tags
        self.wfile.write(b'''
            </body>
            </html>
        ''')


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


def run():
    server = ThreadingSimpleServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()


if __name__ == '__main__':
    run()
