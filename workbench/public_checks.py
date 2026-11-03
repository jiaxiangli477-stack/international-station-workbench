"""Limit the public-company verifier to public HTTP destinations and redirects."""
import ipaddress
import http.client
import socket
import ssl
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPHandler, HTTPSHandler, ProxyHandler, build_opener

def _public_addresses(host, port):
    if host.lower() in ('localhost', 'server') or host.lower().endswith(('.local', '.internal', '.lan')):
        raise ValueError('Local destination is not a public company source')
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Non-public destination')
    return addresses

def _public_socket(host, port, timeout, source_address=None):
    if port not in (80, 443):
        raise ValueError('Non-public service port')
    # Connect numeric sockaddr directly, avoiding create_connection's DNS lookup.
    addresses = _public_addresses(host, port)
    error = None
    for family, kind, proto, _, address in addresses:
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(address)
            return sock
        except OSError as exc:
            error = exc
            sock.close()
    raise error

class PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        if self._tunnel_host:
            raise ValueError('Proxies are disabled for public verification')
        self.sock = _public_socket(self.host, self.port, self.timeout, self.source_address)

class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._tunnel_host or not self._context.check_hostname or self._context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError('Verified direct TLS is required')
        sock = _public_socket(self.host, self.port, self.timeout, self.source_address)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise

class PublicHTTPHandler(HTTPHandler):
    def http_open(self, req):
        require_public_url(req.full_url)
        return self.do_open(PublicHTTPConnection, req)

class PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        require_public_url(req.full_url)
        return self.do_open(PublicHTTPSConnection, req, context=self._context)

def build_public_opener():
    # System/environment proxies must not resolve or route around this boundary.
    return build_opener(ProxyHandler({}), PublicHTTPHandler(),
                        PublicHTTPSHandler(context=ssl.create_default_context()), PublicRedirect())

def require_public_url(url):
    value=urlsplit(url)
    if value.scheme not in ('https','http') or not value.hostname or value.username or value.password:
        raise ValueError('Invalid public URL')
    if value.port not in (None,80,443):raise ValueError('Non-public service port')
    if value.hostname.lower() in ('localhost','server') or value.hostname.lower().endswith(('.local','.internal','.lan')):
        raise ValueError('Local destination is not a public company source')
    addresses=socket.getaddrinfo(value.hostname,value.port or (443 if value.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Non-public destination')
    return url

class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        require_public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
