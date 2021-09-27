#!/usr/bin/python3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import requests

PORT = 80
REGION = os.getenv('REGION', 'all')
CHUNKSIZE = int(os.getenv('CHUNK_SIZE', 64 * 1024))

PLAYLIST_URL = '/playlist.m3u'
EPG_URL = '/epg.xml'
STATUS_URL = '/'

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {
            PLAYLIST_URL: self._playlist,
            EPG_URL: self._epg,
            STATUS_URL: self._status,
        }

        if self.path not in routes:
            self.send_response(404)
            self.end_headers()
            return

        routes[self.path]()

    def _playlist(self):
        self._proxy(f'https://i.mjh.nz/SamsungTVPlus/{REGION}.m3u8')

    def _epg(self):
        self._proxy(f'https://i.mjh.nz/SamsungTVPlus/{REGION}.xml')

    def _proxy(self, url):
        resp = requests.get(url)
        self.send_response(resp.status_code)
        self.send_header('content-type', resp.headers.get('content-type'))
        self.end_headers()
        if resp.ok:
            for chunk in requests.get(url).iter_content(CHUNKSIZE):
                self.wfile.write(chunk)
        else:
            self.wfile.write(f'{url} returned error {resp.status_code}\nCheck your REGION is correct'.encode('utf8'))

    def _status(self):
        self.send_response(200)
        self.end_headers()
        host = self.headers.get('Host')
        self.wfile.write(f'Playlist URL: http://{host}{PLAYLIST_URL}\nEPG URL: http://{host}{EPG_URL}'.encode('utf8'))

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

def run():
    server = ThreadingSimpleServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()

if __name__ == '__main__':
    run()
