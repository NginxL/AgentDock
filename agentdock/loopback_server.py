"""Loopback-only HTTP listener that never needs host-name or reverse-DNS lookup."""

import sys
from http.server import ThreadingHTTPServer
from socketserver import TCPServer

from .diagnostics import failure


class LoopbackServer(ThreadingHTTPServer):
    def server_bind(self):
        if self.server_address[0] != "127.0.0.1":
            raise ValueError("Only IPv4 loopback listeners are supported")
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def handle_error(self, request, client_address):
        error = sys.exception()
        if error is not None:
            failure(error, "api")
