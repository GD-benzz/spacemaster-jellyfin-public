import os
import sys
import socket
import threading
import re
import json
import time
from urllib.parse import urlparse

LOG_FILE = os.environ.get('PROXY_LOG', '/opt/sm/proxy.log')

_REQ_LOCK = threading.Lock()
_REQ_SEQ = 0


def _log(msg):
    print('[profile-proxy] %s %s' % (time.strftime('%Y-%m-%dT%H:%M:%S'), msg), flush=True)


def _flog(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write('[%s] %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%S'), msg))
    except Exception:
        pass


def _req_inc():
    global _REQ_SEQ
    with _REQ_LOCK:
        _REQ_SEQ += 1
        return _REQ_SEQ


def _extract_audio_codecs(body_bytes):
    try:
        data = json.loads(body_bytes.decode('utf-8'))
    except Exception:
        return '(body 非 JSON)'
    dp = data.get('DeviceProfile')
    if not isinstance(dp, dict):
        return '(无 DeviceProfile 字段)'
    dpp = dp.get('DirectPlayProfiles', [])
    tp = dp.get('TranscodingProfiles', [])
    def _ac(lst):
        if not isinstance(lst, list):
            return '(非列表)'
        return [p.get('AudioCodec') for p in lst]
    return 'DirectPlay=%s | Transcode=%s' % (_ac(dpp), _ac(tp))


def _filter_codecs(ac, strip_set):
    if not isinstance(ac, str) or not ac:
        return None
    codecs = [c.strip() for c in ac.split(',') if c.strip()]
    filtered = [c for c in codecs if c.lower() not in strip_set]
    return filtered


def _strip_dp(profiles, strip_set):
    changed = False
    if isinstance(profiles, list):
        for p in profiles:
            ac = p.get('AudioCodec')
            filtered = _filter_codecs(ac, strip_set)
            if filtered is None:
                continue
            if len(filtered) != len([c for c in ac.split(',') if c.strip()]):
                p['AudioCodec'] = ','.join(filtered) if filtered else '_none_'
                changed = True
    return changed


def _strip_tc(profiles, strip_set):
    changed = False
    if isinstance(profiles, list):
        for p in profiles:
            ac = p.get('AudioCodec')
            filtered = _filter_codecs(ac, strip_set)
            if filtered is None:
                continue
            if len(filtered) != len([c for c in ac.split(',') if c.strip()]):
                p['AudioCodec'] = ','.join(filtered) if filtered else ac
                changed = True
    return changed


def _strip_body(body_bytes, dp_strip_set, tc_strip_set):
    try:
        data = json.loads(body_bytes.decode('utf-8'))
    except Exception:
        return None
    dp = data.get('DeviceProfile')
    if not isinstance(dp, dict):
        return None
    changed = False
    changed |= _strip_dp(dp.get('DirectPlayProfiles', []), dp_strip_set)
    changed |= _strip_tc(dp.get('TranscodingProfiles', []), tc_strip_set)
    return data if changed else None


def _pipe(src, dst):
    try:
        while True:
            d = src.recv(4096)
            if not d:
                break
            dst.sendall(d)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def _tunnel_response(client, server, is_upgrade, tag=''):
    resp_header = b''
    while b'\r\n\r\n' not in resp_header:
        c = server.recv(4096)
        if not c:
            return
        resp_header += c
    idx = resp_header.index(b'\r\n\r\n')
    head = resp_header[:idx]
    rest = resp_header[idx + 4:]

    if not is_upgrade:
        lines = head.split(b'\r\n')
        out_lines = [lines[0]]
        for line in lines[1:]:
            k = line.split(b':', 1)[0].decode('latin1').strip().lower()
            if k in ('connection', 'keep-alive', 'proxy-connection'):
                continue
            out_lines.append(line)
        out_lines.append(b'Connection: close')
        head = b'\r\n'.join(out_lines)

    try:
        client.sendall(head + b'\r\n\r\n')
    except Exception:
        return

    if is_upgrade:
        if rest:
            try:
                client.sendall(rest)
            except Exception:
                return
        t1 = threading.Thread(target=_pipe, args=(server, client))
        t2 = threading.Thread(target=_pipe, args=(client, server))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        return

    hdr = {}
    for line in head.split(b'\r\n')[1:]:
        if b':' in line:
            k, v = line.split(b':', 1)
            hdr[k.decode('latin1').strip().lower()] = v.decode('latin1').strip()
    cl = hdr.get('content-length')
    total = 0
    err = None
    try:
        if rest:
            client.sendall(rest)
            total += len(rest)
        if cl is not None:
            n = int(cl)
            while n > 0:
                d = server.recv(min(65536, n))
                if not d:
                    break
                client.sendall(d)
                total += len(d)
                n -= len(d)
        else:
            while True:
                d = server.recv(65536)
                if not d:
                    break
                client.sendall(d)
                total += len(d)
    except Exception as e:
        err = e
    finally:
        try:
            client.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        try:
            server.close()
        except Exception:
            pass
    if err or ('.ts' not in tag and 'm3u8' not in tag):
        _flog('RESP %s bytes=%d cl=%s err=%s' % (tag, total, cl, err))


def _handle_client(client, up_host, up_port, dp_strip_set, tc_strip_set, enable, peq_active):
    server = None
    try:
        client.settimeout(120)
        peer = client.getpeername()
        header_buf = b''
        while b'\r\n\r\n' not in header_buf:
            chunk = client.recv(4096)
            if not chunk:
                return
            header_buf += chunk
            if len(header_buf) > 65536:
                break
        header_end = header_buf.index(b'\r\n\r\n') + 4
        header_part = header_buf[:header_end]
        body = header_buf[header_end:]
        lines = header_part.split(b'\r\n')
        request_line = lines[0].decode('latin1')
        parts = request_line.split(' ')
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1]
        headers = {}
        for line in lines[1:]:
            if b':' in line:
                k, v = line.split(b':', 1)
                headers[k.decode('latin1').strip().lower()] = v.decode('latin1').strip()
        content_length = int(headers.get('content-length', '0') or '0')
        expect_100 = '100-continue' in headers.get('expect', '').lower()

        _flog('REQ #%d %s %s from %s' % (_req_inc(), method, path, peer))

        if expect_100:
            try:
                client.sendall(b'HTTP/1.1 100 Continue\r\n\r\n')
            except Exception:
                return

        while len(body) < content_length:
            chunk = client.recv(4096)
            if not chunk:
                break
            body += chunk

        is_playback = (method.upper() == 'POST'
                       and re.match(r'^/Items/[^/]+/PlaybackInfo(\?|$)', path, re.I))
        forward_body = body
        modified = False
        if enable and is_playback and body and peq_active():
            ac_before = _extract_audio_codecs(body)
            stripped = _strip_body(body, dp_strip_set, tc_strip_set)
            if stripped is not None:
                forward_body = json.dumps(stripped).encode('utf-8')
                modified = True
                ac_after = _extract_audio_codecs(forward_body)
                _flog('PlaybackInfo peq=ON 抠除前 AudioCodec=%s -> 抠除后=%s (dp_strip=%s tc_strip=%s)'
                      % (ac_before, ac_after, ','.join(sorted(dp_strip_set)), ','.join(sorted(tc_strip_set))))
            else:
                _flog('PlaybackInfo peq=ON 但无音频编码可抠 (AudioCodec=%s, dp_strip=%s)'
                      % (ac_before, ','.join(sorted(dp_strip_set))))
        elif is_playback:
            _flog('PlaybackInfo 未处理: enable=%s body_len=%d peq_active=%s'
                  % (enable, len(body), peq_active()))

        server = socket.create_connection((up_host, up_port), timeout=30)
        server.settimeout(60)
        out_lines = [('%s %s HTTP/1.1' % (method, path)).encode('latin1')]
        for k, v in headers.items():
            if k in ('host', 'content-length', 'proxy-connection',
                     'connection', 'keep-alive', 'expect'):
                continue
            out_lines.append(('%s: %s' % (k, v)).encode('latin1'))
        out_lines.append(('Host: %s' % up_host).encode('latin1'))
        out_lines.append(('Content-Length: %d' % len(forward_body)).encode('latin1'))
        out_lines.append(b'Connection: close')
        server.sendall(b'\r\n'.join(out_lines) + b'\r\n\r\n')
        if forward_body:
            server.sendall(forward_body)

        if modified:
            _log('PEQ=ON stripped dp=%s tc=%s from %s'
                 % (','.join(sorted(dp_strip_set)), ','.join(sorted(tc_strip_set)), path))
        elif enable and is_playback and body and not peq_active():
            _log('PEQ=OFF passthrough (%s)' % path)

        is_upgrade = 'upgrade' in headers
        _tunnel_response(client, server, is_upgrade, tag='%s %s' % (method, path))
    except Exception as e:
        _log('client error: %s' % e)
        _flog('client error: %s' % e)
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            if server is not None:
                server.close()
        except Exception:
            pass


def start_proxy(upstream, listen_port, strip_audio, enable, peq_file='/opt/sm/peq_af.txt'):
    up = urlparse(upstream)
    up_host = up.hostname
    up_port = up.port or 80
    tc_strip_set = set(c.lower() for c in strip_audio if c)
    dp_strip_set = {'aac', 'aac_latm', 'mp3', 'ac3', 'eac3', 'opus',
                    'dca', 'dts', 'truehd', 'mlp'}

    def peq_active():
        try:
            with open(peq_file, 'r', encoding='utf-8') as f:
                return len(f.read().strip()) > 0
        except Exception:
            return False

    _log('listening :%d -> %s (strip=%s, peq_switch=%s)' % (
        listen_port, upstream, ','.join(strip_audio) if enable else 'OFF', peq_file))
    _flog('=== proxy 启动 listening :%d -> %s (strip=%s) ==='
          % (listen_port, upstream, ','.join(strip_audio) if enable else 'OFF'))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', listen_port))
    srv.listen(64)
    while True:
        try:
            client, _ = srv.accept()
        except Exception:
            continue
        t = threading.Thread(
            target=_handle_client,
            args=(client, up_host, up_port, dp_strip_set, tc_strip_set, enable, peq_active),
            daemon=True,
        )
        t.start()


if __name__ == '__main__':
    start_proxy(
        upstream=os.environ.get('UPSTREAM', 'http://127.0.0.1:8096'),
        listen_port=int(os.environ.get('LISTEN_PORT', '8097')),
        strip_audio=os.environ.get('STRIP_AUDIO', 'aac,aac_latm,mp3').split(','),
        enable=os.environ.get('ENABLE', 'true') != 'false',
        peq_file=os.environ.get('PEQ_FILE', '/opt/sm/peq_af.txt'),
    )
