"""Keep WSL alive and bridge only existing Windows loopback services.

The download proxy listens on WSL loopback. Model access listens on Docker's
private bridge address, so the Windows model server stays on 127.0.0.1.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import urllib.request
import select
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def windows_socket(port):
    conn=socket.create_connection(('127.0.0.1',port),timeout=15)
    conn.settimeout(None)
    def feed():
        try:
            while True:
                data=os.read(sys.stdin.fileno(),65536)
                if not data:break
                conn.sendall(data)
        except OSError:pass
        finally:
            try:conn.shutdown(socket.SHUT_WR)
            except OSError:pass
    threading.Thread(target=feed,daemon=True).start()
    try:
        while True:
            data=conn.recv(65536)
            if not data:break
            sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
    finally:conn.close()

def windows_model():
    req=json.loads(sys.stdin.buffer.read().decode('utf-8'))
    if req['path'] not in ('/api/chat','/api/tags','/api/show'):raise ValueError('Unsupported model endpoint')
    request=urllib.request.Request('http://127.0.0.1:11434'+req['path'],data=req.get('body','').encode('utf-8') if req['method']=='POST' else None,headers={'Content-Type':'application/json'},method=req['method'])
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=240) as response:
        sys.stdout.buffer.write(response.read())

def bridge_token():
    env=Path(__file__).resolve().parents[1]/'.env'
    for line in env.read_text('utf-8-sig').splitlines():
        if line.startswith('MODEL_BRIDGE_TOKEN='):return line.split('=',1)[1].strip()
    raise RuntimeError('MODEL_BRIDGE_TOKEN is not configured')

def windows_server(host,proxy_port):
    token=bridge_token()
    allowed_network=ipaddress.ip_network(host+'/20',strict=False)
    class ProxyHandler(socketserver.BaseRequestHandler):
        def handle(self):
            if ipaddress.ip_address(self.client_address[0]) not in allowed_network:return
            data=b''
            self.request.settimeout(20)
            while b'\r\n\r\n' not in data and len(data)<16384:
                chunk=self.request.recv(4096)
                if not chunk:return
                data+=chunk
            first=data.split(b'\r\n',1)[0].decode('ascii','replace').split()
            if len(first)<2 or first[0]!='CONNECT':return
            remote=first[1].rsplit(':',1)[0].lower()
            domains=('docker.io','docker.com','cloudflare.docker.com','github.com','githubusercontent.com','huggingface.co','ollama.com','weaviate.io','quay.io','cloudflarestorage.com')
            if not any(remote==d or remote.endswith('.'+d) for d in domains):
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n');return
            with socket.create_connection(('127.0.0.1',proxy_port),timeout=15) as conn:
                conn.sendall(data);conn.settimeout(None);self.request.settimeout(None)
                while True:
                    readable,_,_=select.select([self.request,conn],[],[],90)
                    if not readable:return
                    for sock in readable:
                        chunk=sock.recv(65536)
                        if not chunk:return
                        (conn if sock is self.request else self.request).sendall(chunk)
    class ProxyServer(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    network=ProxyServer((host,17897),ProxyHandler)
    threading.Thread(target=network.serve_forever,daemon=True).start()
    class WindowsModelHandler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def process(self):
            if ipaddress.ip_address(self.client_address[0]) not in allowed_network or self.headers.get('X-Bridge-Token')!=token:
                self.send_error(403);return
            if self.path not in ('/api/chat','/api/tags','/api/show'):self.send_error(404);return
            length=int(self.headers.get('Content-Length','0'))
            if length>6_000_000:self.send_error(413);return
            body=self.rfile.read(length) if length else None
            try:
                req=urllib.request.Request('http://127.0.0.1:11434'+self.path,data=body,headers={'Content-Type':'application/json'},method=self.command)
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(req,timeout=240) as r:result=r.read()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
            except Exception:self.send_error(503,'Local model unavailable')
        do_GET=process
        do_POST=process
    print('Private WSL bridges started',flush=True)
    ThreadingHTTPServer((host,11435),WindowsModelHandler).serve_forever()

def linux_server(windows_host, proxy_port):
    token=bridge_token()
    class ProxyHandler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection((windows_host,17897),timeout=10) as conn:
                while True:
                    readable,_,_=select.select([self.request,conn],[],[],90)
                    if not readable:return
                    for sock in readable:
                        data=sock.recv(65536)
                        if not data:return
                        (conn if sock is self.request else self.request).sendall(data)
    class ProxyServer(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    server=ProxyServer(('127.0.0.1',17897),ProxyHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    config = Path('/etc/systemd/system/docker.service.d/emotion-dog-proxy.conf')
    content = ('[Service]\nEnvironment="HTTP_PROXY=http://127.0.0.1:17897" '
               '"HTTPS_PROXY=http://127.0.0.1:17897" '
               '"NO_PROXY=localhost,127.0.0.1,::1"\n')
    changed = not config.exists() or config.read_text() != content
    if changed:
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(content)
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
    subprocess.run(['systemctl','restart' if changed else 'start','docker'],check=True,timeout=120)
    bridge_ip=subprocess.check_output(['docker','network','inspect','bridge','--format','{{(index .IPAM.Config 0).Gateway}}'],text=True,timeout=20).strip()
    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def process(self):
            if self.path not in ('/api/chat','/api/tags','/api/show'):
                self.send_error(404);return
            length=int(self.headers.get('Content-Length','0'))
            if length>6_000_000:self.send_error(413);return
            body=self.rfile.read(length).decode('utf-8')
            try:
                req=urllib.request.Request(f'http://{windows_host}:11435'+self.path,data=body.encode('utf-8') if self.command=='POST' else None,headers={'Content-Type':'application/json','X-Bridge-Token':token},method=self.command)
                with urllib.request.urlopen(req,timeout=240) as r:result=r.read()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
            except Exception:self.send_error(503,'Local model unavailable')
        do_GET=process
        do_POST=process
    try:
        model=ThreadingHTTPServer((bridge_ip,11434),ModelHandler)
        print(f'Model bridge: Docker private bridge {bridge_ip}:11434; download proxy: 127.0.0.1:17897',flush=True)
        model.serve_forever()
    finally:server.shutdown()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['linux','windows-socket','windows-model','windows-server']);p.add_argument('value',nargs='?');p.add_argument('--proxy-port',type=int,default=7897);args=p.parse_args()
    if args.mode=='windows-socket':windows_socket(int(args.value))
    elif args.mode=='windows-model':windows_model()
    elif args.mode=='windows-server':windows_server(args.value,args.proxy_port)
    else:linux_server(args.value,args.proxy_port)
