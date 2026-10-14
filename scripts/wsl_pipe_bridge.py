"""Bridge local services through a Windows-owned WSL process's standard I/O.

No Windows inbound listener is needed. HTTPS remains end-to-end through the
existing Windows download proxy; the model remains on Windows loopback.
"""
import argparse
import base64
import ipaddress
import json
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOMAINS = ('docker.io', 'docker.com', 'cloudfront.docker.com', 'github.com',
           'githubusercontent.com', 'huggingface.co', 'ollama.com',
           'weaviate.io', 'quay.io', 'cloudflarestorage.com', 'ubuntu.com')
write_lock = threading.Lock()


def send(output, message):
    with write_lock:
        output.write((json.dumps(message, separators=(',', ':')) + '\n').encode())
        output.flush()


def windows(distro, proxy_port):
    project = Path(__file__).resolve().parents[1]
    logs = project.parents[1] / '05_日志'
    path = '/mnt/' + str(project.drive)[0].lower() + str(Path(__file__).resolve())[2:].replace('\\', '/')
    with (logs / 'wsl-pipe-linux.stderr.log').open('ab') as errors:
        process = subprocess.Popen(['wsl', '-d', distro, '-u', 'root', '--exec',
                                    'python3', '-u', path, 'linux'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
        connections = {}

        def proxy_open(message):
            identity = message['id']
            connection = None
            try:
                remote = message['remote']
                host, port = remote.rsplit(':', 1)
                host = host.lower()
                if port != '443' or not any(host == domain or host.endswith('.' + domain) for domain in DOMAINS):
                    raise ValueError('Unsupported download destination')
                connection = socket.create_connection(('127.0.0.1', proxy_port), timeout=15)
                connections[identity] = connection
                connection.sendall(f'CONNECT {remote} HTTP/1.1\r\nHost: {remote}\r\n\r\n'.encode())
                connection.settimeout(None)
                while data := connection.recv(65536):
                    send(process.stdin, {'type': 'data', 'id': identity,
                                         'data': base64.b64encode(data).decode()})
            except (OSError, ValueError):
                pass
            finally:
                connections.pop(identity, None)
                if connection:
                    connection.close()
                try:
                    send(process.stdin, {'type': 'close', 'id': identity})
                except (OSError, ValueError):
                    pass

        def model(message):
            result = {'type': 'result', 'id': message['id'], 'status': 503, 'data': ''}
            try:
                if message['path'] not in ('/api/chat', '/api/tags', '/api/show'):
                    raise ValueError('Unsupported model endpoint')
                body = base64.b64decode(message['data'])
                if len(body) > 6_000_000:
                    raise ValueError('Model request too large')
                request = urllib.request.Request('http://127.0.0.1:11434' + message['path'],
                    data=body if message['method'] == 'POST' else None,
                    headers={'Content-Type': 'application/json'}, method=message['method'])
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=240) as response:
                    data = response.read()
                    result.update(status=response.status, data=base64.b64encode(data).decode())
            except Exception:
                pass
            send(process.stdin, result)

        try:
            print('WSL pipe bridge starting: ' + distro, flush=True)
            for line in process.stdout:
                message = json.loads(line)
                kind = message['type']
                if kind == 'open':
                    threading.Thread(target=proxy_open, args=(message,), daemon=True).start()
                elif kind == 'data':
                    connection = connections.get(message['id'])
                    if connection:
                        try:
                            connection.sendall(base64.b64decode(message['data']))
                        except OSError:
                            connection.close()
                elif kind == 'close':
                    connection = connections.pop(message['id'], None)
                    if connection:
                        connection.close()
                elif kind == 'model':
                    threading.Thread(target=model, args=(message,), daemon=True).start()
                elif kind == 'status':
                    print(message['message'], flush=True)
            if process.wait() != 0:
                raise RuntimeError('WSL bridge process ended unexpectedly')
        finally:
            for connection in list(connections.values()):
                connection.close()
            process.stdin.close()
            process.terminate()


def linux():
    clients = {}
    responses = {}
    stopped = threading.Event()

    def read():
        try:
            for line in sys.stdin.buffer:
                message = json.loads(line)
                identity = message.get('id')
                if message['type'] == 'data':
                    connection = clients.get(identity)
                    if connection:
                        connection.sendall(base64.b64decode(message['data']))
                elif message['type'] == 'close':
                    connection = clients.pop(identity, None)
                    if connection:
                        connection.shutdown(socket.SHUT_RDWR)
                        connection.close()
                elif message['type'] == 'result' and identity in responses:
                    event, result = responses[identity]
                    result.update(message)
                    event.set()
        except (OSError, ValueError):
            pass
        finally:
            stopped.set()

    class Proxy(socketserver.BaseRequestHandler):
        def handle(self):
            identity = uuid.uuid4().hex
            try:
                self.request.settimeout(20)
                header = b''
                while b'\r\n\r\n' not in header and len(header) < 16384:
                    data = self.request.recv(4096)
                    if not data:
                        return
                    header += data
                fields = header.split(b'\r\n', 1)[0].decode('ascii').split()
                if len(fields) != 3 or fields[0] != 'CONNECT':
                    return
                clients[identity] = self.request
                send(sys.stdout.buffer, {'type': 'open', 'id': identity, 'remote': fields[1]})
                self.request.settimeout(None)
                while data := self.request.recv(65536):
                    send(sys.stdout.buffer, {'type': 'data', 'id': identity,
                                             'data': base64.b64encode(data).decode()})
            except (OSError, ValueError):
                pass
            finally:
                clients.pop(identity, None)
                send(sys.stdout.buffer, {'type': 'close', 'id': identity})

    class ProxyServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    proxy = ProxyServer(('127.0.0.1', 17897), Proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    threading.Thread(target=read, daemon=True).start()
    send(sys.stdout.buffer, {'type': 'status', 'message': 'WSL private download proxy ready'})

    def start_model():
        # Docker installation can complete while this same proxy stays alive.
        while not stopped.wait(2):
            try:
                gateway = subprocess.check_output(['docker', 'network', 'inspect', 'bridge',
                    '--format', '{{(index .IPAM.Config 0).Gateway}}'], stderr=subprocess.DEVNULL,
                    text=True, timeout=10).strip()
                if not ipaddress.ip_address(gateway).is_private:
                    raise ValueError('Expected private Docker gateway')
                break
            except (FileNotFoundError, subprocess.SubprocessError, ValueError):
                continue
        else:
            return

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_model(self):
                if self.path not in ('/api/chat', '/api/tags', '/api/show'):
                    self.send_error(404)
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if length > 6_000_000:
                    self.send_error(413)
                    return
                identity = uuid.uuid4().hex
                event, result = threading.Event(), {}
                responses[identity] = (event, result)
                try:
                    send(sys.stdout.buffer, {'type': 'model', 'id': identity, 'path': self.path,
                        'method': self.command, 'data': base64.b64encode(self.rfile.read(length)).decode()})
                    if not event.wait(250):
                        self.send_error(504)
                        return
                    data = base64.b64decode(result['data'])
                    self.send_response(result['status'])
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                finally:
                    responses.pop(identity, None)

            do_GET = handle_model
            do_POST = handle_model

        server = ThreadingHTTPServer((gateway, 11434), Model)
        send(sys.stdout.buffer, {'type': 'status', 'message': 'Docker private model bridge ready'})
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stopped.wait()
        server.shutdown()

    threading.Thread(target=start_model, daemon=True).start()
    stopped.wait()
    proxy.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['windows', 'linux'])
    parser.add_argument('distro', nargs='?', default='EmotionDogUbuntu')
    parser.add_argument('--proxy-port', type=int, default=7897)
    args = parser.parse_args()
    if args.mode == 'windows':
        windows(args.distro, args.proxy_port)
    else:
        linux()
