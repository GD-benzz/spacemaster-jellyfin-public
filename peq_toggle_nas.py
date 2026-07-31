#!/usr/bin/env python3





import json, os, shutil, time, threading
import urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PEQ_AF    = os.environ.get("PEQ_AF",   "/opt/sm/peq_af.txt")
PEQ_GEN   = os.environ.get("PEQ_GEN",  "/opt/sm/peq_gen.json")
PEQ_JSON  = os.environ.get("PEQ_JSON", "/opt/sm/peq.json")
PEQ_DELAY = os.environ.get("PEQ_DELAY","/opt/sm/peq_delay.txt")
DOWNMIX   = os.environ.get("DOWNMIX",  "/opt/sm/downmix.env")
PORT      = int(os.environ.get("PORT", "8777"))




MSG = {
    "zh": {
        "jf_not_cfg_reload": "未配置 Jellyfin，无法重载（文件已写，播放时生效）",
        "jf_conn_err": "无法连接 Jellyfin: %s",
        "no_active_play": "当前没有正在播放的内容（已保存，播放时生效）",
        "tv_seek_hint": "EQ 已保存。TV 端请在播放器里把进度条拖动 1~2 秒即可听到新效果（TV 应用不支持远程重载；此方式不打断播放、不会反复卡）。",
        "gentle_reload": "已温和重载（拆旧转码+清缓存，不重启容器）；客户端续播即从新位置应用新 EQ",
        "seek_reload": "已远程重载（Web 端 seek 触发新转码，重读新 EQ）；约 1~2s 内无缝续播",
        "jf_not_cfg": "未配置 Jellyfin 连接",
        "replay_busy": "正在应用中，请稍候",
        "replay_triggered": "已触发重播",
        "peq_off_ok": "PEQ 已关闭，下次播放生效",
        "params_saved_ok": "参数已保存，下次播放时生效",
        "client_resume_note": "（客户端续播即生效，约几秒）",
        "double_eq_head": "检测到 Windows 客户端正在串流 NAS 音效（%s）。",
        "double_eq_tail": "NAS 已在服务端把音效烤进音频，请勿在该 Windows 电脑上再开启「空间大师 Win 版」（CamillaDSP / Equalizer APO），否则同一路声音会被加两次 EQ，导致双重音效、发闷发刺。Win 版仅用于「Windows 电脑本地直接播放影片」的场景。",
    },
    "en": {
        "jf_not_cfg_reload": "Jellyfin not configured; cannot reload (file written, applies on playback)",
        "jf_conn_err": "Cannot connect to Jellyfin: %s",
        "no_active_play": "Nothing is currently playing (saved; applies on playback)",
        "tv_seek_hint": "EQ saved. On the TV app, drag the progress bar 1–2 seconds to hear the new effect (the TV app does not support remote reload; this does not interrupt playback or cause repeated stalling).",
        "gentle_reload": "Gentle reload done (old transcode torn down + cache cleared, container not restarted); new EQ applies when the client resumes",
        "seek_reload": "Remote reload done (Web seek triggers a new transcode that re-reads the new EQ); seamless resume within ~1–2s",
        "jf_not_cfg": "Jellyfin connection not configured",
        "replay_busy": "Applying, please wait",
        "replay_triggered": "Reload triggered",
        "peq_off_ok": "PEQ turned off; takes effect on next playback",
        "params_saved_ok": "Parameters saved; takes effect on next playback",
        "client_resume_note": " (takes effect when the client resumes, ~a few seconds)",
        "double_eq_head": "Detected a Windows client streaming NAS audio (%s). ",
        "double_eq_tail": "The NAS has already baked the sound into the audio on the server side. Do NOT also enable “SpaceMaster Win edition” (CamillaDSP / Equalizer APO) on that Windows PC, otherwise the same audio would be EQ'd twice, causing a doubled, muffled/harsh sound. The Win edition is only meant for playing movies directly on the Windows PC itself.",
    },
}

def M(key, lang="zh", *a):
    d = MSG.get(lang, MSG["zh"])
    s = d.get(key, MSG["zh"].get(key, key))
    if a:
        try:
            return s % a
        except Exception:
            return s
    return s



GEN_DEFAULT = {"L":3.1,"W":4.4,"H":2.8,"sys":"tv","low":0.0,"mid":0.7,"hi":1.5,
               "delayManual":{"FL":0.0,"FR":0.0,"FC":0.0,"SL":0.0,"SR":0.0,"LFE":0.0}}


def read_peq():
    try:
        s = open(PEQ_AF).read().strip()
    except FileNotFoundError:
        return False, []
    if not s:
        return False, []
    bands = []
    for part in s.split(','):
        part = part.strip()
        if part.startswith('equalizer='):
            part = part[len('equalizer='):]
            ptype = None
        elif part.startswith('lowshelf='):
            part = part[len('lowshelf='):]
            ptype = 'lowshelf'
        else:
            ptype = None
        d = {}
        for kv in part.split(':'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                d[k] = v
        if 'f' in d and 'g' in d:
            band = {"f": float(d['f']), "g": float(d['g']),
                    "Q": float(d.get('w', d.get('q', 1)))}
            if ptype == 'lowshelf':
                band["t"] = "lowshelf"
            bands.append(band)
    return True, bands


def write_peq(bands):
    parts = []
    for b in bands:
        if b.get('t') == 'lowshelf':
            parts.append("lowshelf=f=%s:g=%s:w=%s:t=q" % (b['f'], b['g'], b.get('Q', 0.7)))
        else:
            parts.append("equalizer=f=%s:g=%s:w=%s:t=q" % (b['f'], b['g'], b['Q']))
    s = ",".join(parts)
    open(PEQ_AF, 'w').write(s)
    try:  
        json.dump({"peq": bands, "meta": {}}, open(PEQ_JSON, 'w'))
    except Exception:
        pass


def read_gen():
    try:
        return json.load(open(PEQ_GEN))
    except Exception:
        return None


def write_gen(g):
    try:
        json.dump(g, open(PEQ_GEN, 'w'))
    except Exception:
        pass


def read_downmix():
    d = {"SM_DOWNMIX": "1", "SM_FL": "1.00", "SM_CENTER": "0.707", "SM_SURR": "0.707",
         "SM_LFE": "0.707", "SM_MAKEUP": "6", "SM_LIMIT": "1.0"}
    try:
        for line in open(DOWNMIX):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                d[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return d


def write_downmix(upd):
    d = read_downmix()
    d.update({k: str(v) for k, v in upd.items()})
    open(DOWNMIX, 'w').write("\n".join("%s=%s" % (k, v) for k, v in d.items()) + "\n")


def sync_downmix_from_sys(gen):
    
    sys_t = (gen or {}).get('sys', 'tv')
    if sys_t == 'ht51':
        dm = '0'
    elif sys_t == 'ht21':
        dm = '2'
    else:
        dm = '1'
    write_downmix({'SM_DOWNMIX': dm})













DELAY_CHANNELS = {
    'tv':   ['FL', 'FR'],
    'ht20': ['FL', 'FR'],
    'ht21': ['FL', 'FR', 'LFE'],
    'ht51': ['FL', 'FR', 'FC', 'SL', 'SR', 'LFE'],
}

def compute_delay_string(gen):
    
    sys_t = (gen or {}).get('sys', 'tv')
    if sys_t not in ('ht20', 'ht21'):
        return None  
    chans = DELAY_CHANNELS.get(sys_t, ['FL', 'FR'])
    man = gen.get('delayManual') or {}
    try:
        total = [round(float(man.get(c, 0)), 2) for c in chans]
    except (TypeError, ValueError):
        return None
    if all(t == 0 for t in total):
        return None  
    return "adelay=delays=" + "|".join(str(t) for t in total)


def write_delay(s):
    
    open(PEQ_DELAY, 'w').write((s or '').strip() + "\n")







def read_jellyfin_cfg():
    p = os.environ.get("JELLYFIN_CFG", "/opt/sm/jellyfin.json")
    try:
        return json.load(open(p))
    except Exception:
        return {}


def write_jellyfin_cfg(cfg):
    p = os.environ.get("JELLYFIN_CFG", "/opt/sm/jellyfin.json")
    try:
        json.dump(cfg, open(p, "w"))
    except Exception:
        pass


def _jf_req(cfg, path, method="GET", body=None):
    
    base = (cfg.get("url") or "").rstrip("/")
    key = cfg.get("key") or ""
    sep = "&" if "?" in path else "?"
    url = base + path + sep + "api_key=" + urllib.parse.quote(key, safe="")
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as r:
        txt = r.read().decode("utf-8", "replace")
        try:
            return json.loads(txt) if txt else {}
        except Exception:
            return {}


def clear_transcode_cache(cfg=None):
    
    dirs = []
    if cfg:
        try:
            sc = _jf_req(cfg, "/System/Configuration")
            tp = sc.get("TranscodingTempPath") or sc.get("TranscodedPath") or ""
            if tp:
                dirs.append(tp)
        except Exception:
            pass
    env = os.environ.get("TRANSCODE_DIR", "")
    if env:
        dirs += [x.strip() for x in env.split(",") if x.strip()]
    if not dirs:
        dirs = ["/var/lib/jellyfin/transcodes", "/var/cache/jellyfin/transcodes",
                "/config/transcodes", "/cache/transcodes", "/opt/sm/transcodes"]
    cleared = []
    for d in dirs:
        if d and os.path.isdir(d):
            try:
                for name in os.listdir(d):
                    p = os.path.join(d, name)
                    if os.path.isfile(p) or os.path.islink(p):
                        os.remove(p)
                    elif os.path.isdir(p):
                        shutil.rmtree(p)
                cleared.append(d)
            except Exception:
                pass
    
    
    
    try:
        import subprocess
        cid = subprocess.check_output(
            ["docker", "ps", "--filter", "name=jellyfin", "--format", "{{.ID}}"],
            stderr=subprocess.DEVNULL).decode().strip().split("\n")[0].strip()
        if cid:
            subprocess.call(["docker", "exec", cid, "sh", "-c",
                "rm -rf /cache/transcodes/* /transcodes/* 2>/dev/null; true"],
                stderr=subprocess.DEVNULL)
            cleared.append("docker:%s:/cache/transcodes" % cid)
    except Exception:
        pass
    return cleared


def _jellyfin_direct_url(cfg):
    
    import re
    u = (cfg.get("url") or "").strip()
    if not u:
        return u
    m = re.match(r'^(https?://[^:/]+):(\d+)(/.*)?$', u)
    if m:
        return '%s:8097%s' % (m.group(1), m.group(3) or '')
    return u


def _clear_full_transcode_dir():
    
    try:
        cid = _sp.check_output(
            ["docker", "ps", "--filter", "name=jellyfin", "--format", "{{.ID}}"],
            stderr=_sp.DEVNULL).decode().strip().split("\n")[0].strip()
        if cid:
            _sp.call(["docker", "exec", cid, "sh", "-c",
                      "rm -rf /cache/transcodes/* 2>/dev/null; true"],
                     stderr=_sp.DEVNULL)
            return "docker:%s:/cache/transcodes" % cid
    except Exception:
        pass
    return ""


def _kill_ffmpeg(cid):
    
    if not cid:
        return
    try:
        _sp.check_call(["docker", "exec", cid, "sh", "-c",
                        "for p in $(pgrep -f ffmpeg 2>/dev/null); do kill -9 $p 2>/dev/null; done; true"],
                       stderr=_sp.DEVNULL)
        print("[replay] 已 kill 残留 ffmpeg", flush=True)
    except Exception:
        pass


def _jf_delete_active_encoding(cfg, dev, pses):
    
    import re
    u = (cfg.get("url") or "").strip()
    m = re.match(r'^(https?://[^:/]+):(\d+)(/.*)?$', u)
    base = '%s:8097%s' % (m.group(1), m.group(3) or '') if m else u
    key = cfg.get("key") or ""
    path = "/Videos/ActiveEncodings?DeviceId=%s&PlaySessionId=%s" % (
        urllib.parse.quote(dev), urllib.parse.quote(pses))
    sep = "&" if "?" in path else "?"
    url = base + path + sep + "api_key=" + urllib.parse.quote(key, safe="")
    req = urllib.request.Request(url, method="DELETE", headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=15) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1


def _jellyfin_restart_reload(cfg, clear_cache=True, lang="zh"):
    
    
    try:
        cid = _sp.check_output(
            ["docker", "ps", "--filter", "name=jellyfin", "--format", "{{.ID}}"],
            stderr=_sp.DEVNULL).decode().strip().split("\n")[0].strip()
    except Exception:
        cid = ""
    if not cid:
        cid = cfg.get("container") or "jellyfin-sm"
    
    try:
        sessions = _jf_req(cfg, "/Sessions")
    except Exception:
        sessions = []
    cur = next((s for s in (sessions or []) if s.get("NowPlayingItem") and s.get("IsActive")), None)
    dev = pses = ""
    if cur:
        ps = cur.get("PlayState") or {}
        dev = cur.get("DeviceId") or ""
        pses = cur.get("PlaySessionId") or ps.get("PlaySessionId") or ""
    if dev and pses:
        code = _jf_delete_active_encoding(cfg, dev, pses)
        print("[replay] DELETE ActiveEncodings 已发 (code=%s, 拆旧转码会话)" % code, flush=True)
    else:
        print("[replay] 未取到活跃会话 DeviceId/PlaySessionId，跳过 DELETE", flush=True)
    
    time.sleep(1.0)
    
    if clear_cache and cid:
        try:
            _sp.call(["docker", "exec", cid, "sh", "-c",
                      "rm -rf /cache/transcodes/* 2>/dev/null; true"],
                     stderr=_sp.DEVNULL)
            print("[replay] 已清 /cache/transcodes/*（旧分片移除）", flush=True)
        except Exception:
            pass
    
    _kill_ffmpeg(cid)
    return True, M("gentle_reload", lang)


def _jellyfin_seek_reload(cfg, session, lang="zh"):
    
    sid = session.get('Id') or ''
    pos = (session.get('PlayState') or {}).get('PositionTicks') or 0
    new_pos = pos + 10000000  
    body = {"Command": "Seek", "SeekPositionTicks": new_pos}
    try:
        _jf_req(cfg, "/Sessions/%s/Playing/PlayState" % urllib.parse.quote(sid, safe=""),
                method="POST", body=body)
        print("[replay] 已远程 Seek(+1s) 触发新转码，重读新 EQ", flush=True)
        return True, M("seek_reload", lang)
    except Exception as e:
        print("[replay] Seek 失败 %s，回退温和拆流" % e, flush=True)
        return _jellyfin_restart_reload(cfg, clear_cache=True, lang=lang)


def replay_active_session(cfg, clear_cache=True, lang="zh"):
    
    if not (cfg.get('url') and cfg.get('key')):
        return False, M("jf_not_cfg_reload", lang), "tv"
    try:
        sessions = _jf_req(cfg, "/Sessions")
    except Exception as e:
        return False, M("jf_conn_err", lang, e), "tv"
    cur = None
    cur_web = None
    for s in (sessions or []):
        if s.get('NowPlayingItem') and s.get('IsActive'):
            if cur is None:
                cur = s
            
            if s.get('SupportsMediaControl') and s.get('Id'):
                cur_web = s
    if cur_web:
        cur = cur_web
    if not cur:
        return False, M("no_active_play", lang), "tv"
    session_id = cur.get('Id') or ''
    device_id = cur.get('DeviceId', '') or ''
    client = cur.get('Client', '') or ''
    play_state = cur.get('PlayState') or {}
    play_session = cur.get('PlaySessionId') or play_state.get('PlaySessionId') or ''
    pos = play_state.get('PositionTicks') or 0
    item = cur.get('NowPlayingItem') or {}
    item_id = item.get('Id', '') or ''
    audio_idx = play_state.get('AudioStreamIndex')
    sub_idx = play_state.get('SubtitleStreamIndex')
    media_src = ''
    ms = item.get('MediaSources') or []
    if ms:
        media_src = (ms[0] or {}).get('Id', '') or ''
    
    if cur.get('SupportsMediaControl') and cur.get('Id'):
        
        ok, msg = _jellyfin_seek_reload(cfg, cur, lang)
        return (ok, msg, "web")
    
    return (True, M("tv_seek_hint", lang), "tv")









import subprocess as _sp

_replay_state = {"status": "idle", "msg": "", "started_at": 0.0}
_replay_lock = threading.Lock()


def _detect_transcode_started(cfg, timeout=90, grace=6.0):
    
    try:
        cid = _sp.check_output(
            ["docker", "ps", "--filter", "name=jellyfin", "--format", "{{.ID}}"],
            stderr=_sp.DEVNULL).decode().strip().split("\n")[0].strip()
        if not cid:
            return False
        
        time.sleep(1.5)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                out = _sp.check_output(
                    ["docker", "exec", cid, "sh", "-c", "pgrep -c ffmpeg 2>/dev/null || echo 0"],
                    stderr=_sp.DEVNULL).decode().strip()
                count = int(out) if out.isdigit() else 0
                if count > 0:
                    print("[replay] 新 ffmpeg 进程检测到 (count=%d)，等待切流 grace=%.1fs" % (count, grace), flush=True)
                    time.sleep(grace)
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def _do_replay(cfg, lang="zh"):
    
    t0 = time.time()
    with _replay_lock:
        _replay_state["status"] = "loading"
        _replay_state["msg"] = "正在应用音效（不重启容器）"
        _replay_state["started_at"] = time.time()
    print("[replay] 开始 (t=%.1fs)" % (time.time() - t0), flush=True)
    res = replay_active_session(cfg, clear_cache=True, lang=lang)
    if isinstance(res, tuple) and len(res) == 3:
        ok, msg, kind = res
    else:
        ok, msg = res
        kind = "gentle"
    if not ok:
        with _replay_lock:
            _replay_state["status"] = "error"
            _replay_state["msg"] = msg
        print("[replay] 失败: %s (t=%.1fs)" % (msg, time.time() - t0), flush=True)
        return
    print("[replay] 已触发温和重载(kind=%s) (t=%.1fs)" % (kind, time.time() - t0), flush=True)
    
    with _replay_lock:
        _replay_state["status"] = "loaded"
        _replay_state["msg"] = msg + M("client_resume_note", lang)
    print("[replay] 完成 kind=%s (t=%.1fs)" % (kind, time.time() - t0), flush=True)


def trigger_replay(cfg, lang="zh"):
    
    if not (cfg.get('url') and cfg.get('key')):
        return True, M("jf_not_cfg_reload", lang)
    with _replay_lock:
        if _replay_state["status"] == "loading":
            
            
            if time.time() - _replay_state.get("started_at", 0) < 120:
                return False, M("replay_busy", lang)
    threading.Thread(target=_do_replay, args=(cfg, lang), daemon=True).start()
    return True, M("replay_triggered", lang)


_DOUBLE_EQ_CACHE = {"ts": 0.0, "data": None}


def _detect_double_eq_risk(cfg, use_cache=True, lang="zh"):
    
    now = time.time()
    if use_cache and _DOUBLE_EQ_CACHE["data"] is not None and (now - _DOUBLE_EQ_CACHE["ts"] < 10):
        return _DOUBLE_EQ_CACHE["data"]
    result = {"windows_streaming": [], "advice": ""}
    try:
        if not (cfg.get('url') and cfg.get('key')):
            raise RuntimeError("no cfg")
        sessions = _jf_req(cfg, "/Sessions")
        for s in (sessions or []):
            if not (s.get('NowPlayingItem') and s.get('IsActive')):
                continue
            client = (s.get('Client') or '').strip()
            os_name = (s.get('OperatingSystem') or '').strip().lower()
            device = (s.get('DeviceName') or '').strip().lower()
            user = (s.get('UserName') or '').strip()
            is_win = False
            if client in ("Jellyfin Web", "Jellyfin Media Player", "Jellyfin Theater"):
                is_win = True
            if "windows" in os_name or "windows" in device:
                is_win = True
            if not is_win:
                continue
            result["windows_streaming"].append({
                "client": client or "未知客户端",
                "device": s.get('DeviceName') or "未知设备",
                "user": user or "未知用户",
            })
    except Exception:
        
        result = {"windows_streaming": [], "advice": ""}
    if result["windows_streaming"]:
        names = "、".join("%s（%s）" % (c["client"], c["device"]) for c in result["windows_streaming"])
        result["advice"] = M("double_eq_head", lang, names) + M("double_eq_tail", lang)
    _DOUBLE_EQ_CACHE["ts"] = time.time()
    _DOUBLE_EQ_CACHE["data"] = result
    return result


def get_replay_state(lang="zh"):
    with _replay_lock:
        state = dict(_replay_state)
    try:
        cfg = read_jellyfin_cfg()
        eq = _detect_double_eq_risk(cfg, lang=lang)
    except Exception:
        eq = {"windows_streaming": [], "advice": ""}
    state["windows_streaming"] = eq["windows_streaming"]
    state["double_eq_advice"] = eq["advice"]
    return state


HTML_PAGE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>空间大师 · 控制台 (8777)</title>
<style>
  :root{--bg:#0f1419;--card:#1a212b;--ink:#e6edf3;--mut:#8b97a6;--acc:#3fb950;--off:#888780;--low:#f0883e;--mid:#58a6ff;--hi:#bc8cff;--comp:#3fb950;--warn:#d29922}
  *{box-sizing:border-box}
  body{font-family:-apple-system,system-ui,sans-serif;background:var(--bg);color:var(--ink);margin:0;padding:20px;max-width:880px;margin:20px auto}
  h1{font-size:20px;margin:0 0 2px}
  .sub{color:var(--mut);font-size:12px;margin-bottom:14px}
  .card{background:var(--card);border-radius:12px;padding:16px;margin-bottom:14px}
  .row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
  label{font-size:12px;color:var(--mut);display:block;margin-bottom:4px}
  input[type=number]{width:84px;padding:8px;border-radius:8px;border:1px solid #2d3744;background:#0d1117;color:var(--ink);font-size:15px}
  select{width:280px;padding:8px;border-radius:8px;border:1px solid #2d3744;background:#0d1117;color:var(--ink);font-size:14px}
  .slider{margin:14px 0}
  .slider .lab{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}
  .slider .val{color:var(--acc);font-variant-numeric:tabular-nums}
  input[type=range]{width:100%;accent-color:var(--acc)}
  .bass input[type=range]{accent-color:var(--low)}
  .mid input[type=range]{accent-color:var(--mid)}
  .hi input[type=range]{accent-color:var(--hi)}
  svg{width:100%;height:200px;background:#0d1117;border-radius:8px;display:block}
  .seg{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--mut);line-height:1.7;max-height:170px;overflow:auto;white-space:pre-wrap}
  textarea{width:100%;height:70px;background:#0d1117;color:var(--acc);border:1px solid #2d3744;border-radius:8px;padding:10px;font-family:ui-monospace,monospace;font-size:11px}
  button{background:var(--acc);color:#04210d;border:none;padding:9px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;margin:4px 6px 4px 0}
  button.sec{background:#21262d;color:var(--ink)}
  button.off{background:var(--off);color:#fff}
  .toggle{position:relative;width:52px;height:28px;border-radius:14px;cursor:pointer;transition:background .2s;flex:0 0 auto}
  .toggle .knob{position:absolute;top:3px;width:22px;height:22px;border-radius:50%;background:#fff;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.4)}
  .toggle.on{background:var(--acc)}
  .toggle.off{background:var(--off)}
  .toggle.on .knob{left:3px}
  .toggle.off .knob{left:27px}
  .note{color:var(--mut);font-size:11px;margin-top:8px;line-height:1.5}
  .pill{display:inline-block;padding:3px 12px;border-radius:20px;font-size:13px;font-weight:600;background:#21262d}
  .pill.on{background:var(--acc);color:#04210d}
  .pill.off{background:var(--off);color:#fff}
  .badge{font-size:11px;color:var(--mut);margin-left:8px}
  .err{color:#f85149;font-size:12px;margin-top:6px;min-height:14px}
  .canvas-wrap{background:#0d1320;border:1px solid #2a3a52;border-radius:8px;padding:6px;margin:6px 0}
  .canvas-wrap canvas{width:100%;height:auto;display:block;border-radius:4px;cursor:crosshair;touch-action:none}
  .canvas-title{font-size:13px;margin:12px 0 2px;color:var(--ink)}
</style>
</head>
<body>
<div style="display:flex;align-items:center;justify-content:space-between;gap:14px">
  <h1 data-i18n="title" style="margin:0">空间大师 · 控制台</h1>
  <div style="display:flex;align-items:center;gap:8px">
    <span data-i18n="lang_label" style="font-size:12px;color:var(--mut)">语言</span>
    <select id="lang" style="width:auto;padding:6px 10px">
      <option value="zh" data-i18n="lang_zh">简体中文</option>
      <option value="en" data-i18n="lang_en">English</option>
    </select>
  </div>
</div>
<div class="sub" data-i18n="sub">端口 8777 · PEQ 开关 + 调整页面。</div>

<div id="eqWarn" style="display:none;margin:0 0 14px;padding:12px 16px;border-radius:12px;background:rgba(248,81,73,.12);border:1px solid #f85149;color:#ffb4ab;font-size:13px;line-height:1.7">
  <b style="color:#f85149" data-i18n="eqwarn_title">⚠ 双重 EQ 提醒</b> <span id="eqWarnMsg"></span>
</div>

<div class="card">
  <div style="display:flex;align-items:center;gap:14px">
    <span data-i18n="peq_label">PEQ 开关：</span>
    <div class="toggle off" id="toggle" data-i18n-title="toggle_title" title="点击切换 开/关"><div class="knob"></div></div>
    <span class="badge" id="statusBands"></span>
  </div>
  <div class="err" id="msg"></div>
</div>

<div class="card">
  <h3 style="margin-top:0" data-i18n="save_title">保存配置</h3>
  <div class="note" style="color:#fff" data-i18n="save_note">每次调整参数后，点「保存配置」（下次播放时生效）。保存后需退出当前影片、重新播放影片，新音效才会生效。</div>
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <button id="applyCurrentBtn" data-i18n="save_title">保存配置</button>
    <span id="pendingBadge" style="display:none;color:var(--warn);font-size:13px;font-weight:600" data-i18n="pending">● 有未保存的更改</span>
  </div>
  <div class="err" id="acMsg"></div>
  <div style="font-size:13px;margin-top:6px;min-height:18px" id="replayStatus"></div>
</div>

<div class="card">
  <div class="row">
    <div><label data-i18n="room_l">房间长 L (m)</label><input id="L" type="number" step="0.1" value="3.1"></div>
    <div><label data-i18n="room_w">房间宽 W (m)</label><input id="W" type="number" step="0.1" value="4.4"></div>
    <div><label data-i18n="room_h">房间高 H (m)</label><input id="H" type="number" step="0.1" value="2.8"></div>
  </div>
  <div style="margin-top:12px">
    <label data-i18n="sys_label">音箱系统类型</label>
    <select id="sys">
      <option value="tv" selected data-i18n="opt_tv">电视机/电脑自带音箱</option>
      <option value="ht51" data-i18n="opt_ht51">家庭影院5.1系统</option>
      <option value="ht21" data-i18n="opt_ht21">立体声2.0/2.1系统</option>
    </select>
  </div>
  <div class="slider bass"><div class="lab"><span data-i18n="bass">低音</span><span class="val" id="lowV">0.0 dB</span></div>
    <input id="low" type="range" min="-10" max="10" step="0.5" value="0"></div>
  <div class="slider mid">    <div class="lab"><span data-i18n="mid">中音</span><span class="val" id="midV">0.0 dB</span></div>
    <input id="mid" type="range" min="-10" max="10" step="0.1" value="0"></div>
  <div class="slider hi"><div class="lab"><span data-i18n="high">高音</span><span class="val" id="hiV">1.5 dB</span></div>
    <input id="hi" type="range" min="-10" max="10" step="0.1" value="1.5"></div>
</div>

<div class="card">
  <label data-i18n="viz_label">均衡响应曲线（频响 · dB）</label>
  <svg id="viz" viewBox="0 0 820 220" style="width:100%;height:auto;display:block"></svg>
</div>

<div class="card" id="delayCard">
  <h3 style="margin-top:0" data-i18n="delay_title">延时校准（独立 2.0/2.1 音箱）</h3>
  <div class="note" data-i18n="delay_note">左 / 右音箱到聆听位的走时差，默认 0ms。</div>
  <div style="display:flex;gap:28px;flex-wrap:wrap;max-width:560px">
    <div class="slider" style="flex:1;min-width:220px">
      <div class="lab"><span data-i18n="delay_l">左音箱延时 (ms)</span>
        <span><input id="dN_FL" type="number" min="0" max="200" step="0.5" value="0" style="width:72px"> ms</span></div>
      <input id="d_FL" type="range" min="0" max="200" step="0.5" value="0">
    </div>
    <div class="slider" style="flex:1;min-width:220px">
      <div class="lab"><span data-i18n="delay_r">右音箱延时 (ms)</span>
        <span><input id="dN_FR" type="number" min="0" max="200" step="0.5" value="0" style="width:72px"> ms</span></div>
      <input id="d_FR" type="range" min="0" max="200" step="0.5" value="0">
    </div>
  </div>
</div>

<div class="card" id="delay51Card" style="display:none">
  <h3 style="margin-top:0" data-i18n="delay51_title">延时校准（家庭影院 5.1）</h3>
  <h3 style="margin:6px 0 0;font-weight:600" data-i18n="delay51_msg">5.1智能延时系统正在升级优化中</h3>
</div>



<script>

const I18N = {
  zh: {
    title: "空间大师 · 控制台",
    sub: "端口 8777 · PEQ 开关 + 调整页面。",
    lang_label: "语言", lang_zh: "简体中文", lang_en: "English",
    eqwarn_title: "⚠ 双重 EQ 提醒",
    peq_label: "PEQ 开关：", toggle_title: "点击切换 开/关",
    save_title: "保存配置",
    save_note: "每次调整参数后，点「保存配置」（下次播放时生效）。保存后需退出当前影片、重新播放影片，新音效才会生效。",
    pending: "● 有未保存的更改",
    room_l: "房间长 L (m)", room_w: "房间宽 W (m)", room_h: "房间高 H (m)",
    sys_label: "音箱系统类型",
    opt_tv: "电视机/电脑自带音箱", opt_ht51: "家庭影院5.1系统", opt_ht21: "立体声2.0/2.1系统",
    bass: "低音", mid: "中音", high: "高音",
    viz_label: "均衡响应曲线（频响 · dB）",
    delay_title: "延时校准（独立 2.0/2.1 音箱）",
    delay_note: "左 / 右音箱到聆听位的走时差，默认 0ms。",
    delay_l: "左音箱延时 (ms)", delay_r: "右音箱延时 (ms)",
    delay51_title: "延时校准（家庭影院 5.1）",
    delay51_msg: "5.1智能延时系统正在升级优化中",
    status_on: "已开启", status_off: "已关闭（透传）",
    wrote_curve: "已写入曲线，点「保存配置」保存",
    wrote_delay: "已写入延时，点「保存配置」保存",
    applying: "● 正在应用音效，请稍候…", applied: "✓ 新音效已生效",
    fail: "失败", proc: "处理中…",
    err_close: "关闭失败: ", err_open: "开启失败: ",
    err_save: "保存失败: ", err_load: "加载状态失败: "
  },
  en: {
    title: "SpaceMaster · Console",
    sub: "Port 8777 · PEQ switch + tuning page.",
    lang_label: "Language", lang_zh: "简体中文", lang_en: "English",
    eqwarn_title: "⚠ Double-EQ Warning",
    peq_label: "PEQ switch:", toggle_title: "Click to toggle on/off",
    save_title: "Save Configuration",
    save_note: "After adjusting any parameter, click “Save Configuration” (takes effect on next playback). After saving, exit the current movie and play it again for the new sound to take effect.",
    pending: "● Unsaved changes",
    room_l: "Room length L (m)", room_w: "Room width W (m)", room_h: "Room height H (m)",
    sys_label: "Speaker system type",
    opt_tv: "TV / built-in PC speakers", opt_ht51: "Home theater 5.1 system", opt_ht21: "Stereo 2.0/2.1 system",
    bass: "Bass", mid: "Mid", high: "Treble",
    viz_label: "Equalizer response curve (frequency · dB)",
    delay_title: "Delay calibration (standalone 2.0/2.1 speakers)",
    delay_note: "Time-of-flight difference between left/right speakers to the listening position. Default 0 ms.",
    delay_l: "Left speaker delay (ms)", delay_r: "Right speaker delay (ms)",
    delay51_title: "Delay calibration (home theater 5.1)",
    delay51_msg: "5.1 smart delay system is being upgraded and optimized",
    status_on: "ON", status_off: "OFF (bypass)",
    wrote_curve: "Curve written, click “Save Configuration” to save",
    wrote_delay: "Delay written, click “Save Configuration” to save",
    applying: "● Applying sound, please wait…", applied: "✓ New sound is active",
    fail: "failed", proc: "Processing…",
    err_close: "Failed to turn off: ", err_open: "Failed to turn on: ",
    err_save: "Failed to save: ", err_load: "Failed to load state: "
  }
};
let currentLang = (localStorage.getItem('sm_lang') === 'en') ? 'en' : 'zh';
function t(key){
  return (I18N[currentLang] && I18N[currentLang][key] != null) ? I18N[currentLang][key]
       : (I18N.zh[key] != null ? I18N.zh[key] : key);
}
function applyLang(lang){
  currentLang = (lang === 'en') ? 'en' : 'zh';
  try { localStorage.setItem('sm_lang', currentLang); } catch(e){}
  document.documentElement.lang = (currentLang === 'en') ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach(el=>{ el.textContent = t(el.getAttribute('data-i18n')); });
  document.querySelectorAll('[data-i18n-title]').forEach(el=>{ el.title = t(el.getAttribute('data-i18n-title')); });
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>{ el.placeholder = t(el.getAttribute('data-i18n-ph')); });
  if (langSel_) langSel_.value = currentLang;
  
  if (statusBands) statusBands.textContent = toggle.classList.contains('on') ? t('status_on') : t('status_off');
  if (lowV) lowV.textContent = (+low_.value).toFixed(1) + ' dB';
  if (midV) midV.textContent = (+mid_.value).toFixed(1) + ' dB';
  if (hiV)  hiV.textContent  = (+hi_.value).toFixed(1) + ' dB';
}

const C = 343;
const CH_LABEL = {FL:'左声道', FR:'右声道', FC:'中置', SL:'左环绕', SR:'右环绕', LFE:'低音炮'};
function axialModes(L,W,H){
  const out=[];
  for(const [name,dim] of [["L",L],["W",W],["H",H]]){
    let n=1;
    while(true){
      const f=n*C/(2*dim);
      if(f>320) break;
      if(f>=30) out.push({f:Math.round(f*10)/10,dim:name});
      n++;
    }
  }
  out.sort((a,b)=>a.f-b.f);
  return out;
}
function mergeModes(raw){
  const merged=[];
  for(const m of raw){
    const hit=merged.find(x=>Math.abs(x.f-m.f)<=5);
    if(hit) hit.coinc++; else merged.push({f:m.f,coinc:1});
  }
  return merged.sort((a,b)=>a.f-b.f);
}
function rawDepth(f,coinc){
  let d=3.8+coinc*1.0+Math.max(0,(250-f))/250*1.3;
  return -Math.min(5.8,Math.max(3.5,d));
}
function qOf(f){ return Math.min(9,Math.max(6,6+f/100)); }
function isBig(sys){ return sys==='ht21'||sys==='ht51'; }
function baseGain(f,coinc,sys){
  const raw=rawDepth(f,coinc);
  let b=(isBig(sys))?(raw*0.4):(raw*0.4*0.4);
  return Math.min(0,b);
}
function build(){
  const L=+L_.value,W=+W_.value,H=+H_.value,sys=sys_.value;
  const low=+low_.value,mid=+mid_.value,hi=+hi_.value;
  const LOW_CUT=isBig(sys)?30:50;
  const modes=mergeModes(axialModes(L,W,H)).filter(m=>m.f>=LOW_CUT);
  const bass=modes.map(m=>{
    const g=baseGain(m.f,m.coinc,sys);   
    return {f:m.f,g:+g.toFixed(2),Q:+qOf(m.f).toFixed(2),t:"bass"};
  });
  const midB={f:1350,g:mid,Q:0.5,t:"mid"};
  const hiB={f:8000,g:hi,Q:1,t:"hi"};
  
  let compB=null;
  if(sys==='tv')        compB={f:300,g:+(2.5+mid).toFixed(2),Q:0.5,t:"comp"};
  else if(sys==='ht21') compB={f:300,g:1.0,Q:1.5,t:"comp"};
  
  
  const shelf=(low!==0)?[{f:200,g:low,Q:0.7,t:"lowshelf"}]:[];
  currentBands=[...bass, ...(compB?[compB]:[]), midB, hiB, ...shelf];
  renderViz(currentBands);
}
function renderViz(bands){
  const W=820,H=220,m=34,fMin=20,fMax=20000,gMin=-12,gMax=14,Fs=48000;
  const lx=f=>(Math.log10(f)-Math.log10(fMin))/(Math.log10(fMax)-Math.log10(fMin))*(W-2*m)+m;
  const ly=g=>m+(gMax-g)/(gMax-gMin)*(H-2*m);
  
  const bqs=bands.map(b=>{
    const A=Math.pow(10,b.g/40), w0=2*Math.PI*b.f/Fs, cw=Math.cos(w0), sw=Math.sin(w0);
    if(b.t==="lowshelf"){
      const S=b.Q, alpha=sw/2*Math.sqrt((A+1/A)*(1/S-1)+2), sq=2*Math.sqrt(A)*alpha;
      return {b0:A*((A+1)-(A-1)*cw+sq), b1:2*A*((A-1)-(A+1)*cw), b2:A*((A+1)-(A-1)*cw-sq),
              a0:(A+1)+(A-1)*cw+sq, a1:-2*((A-1)+(A+1)*cw), a2:(A+1)+(A-1)*cw-sq};
    }
    const al=sw/(2*b.Q);
    return {b0:1+al*A,b1:-2*cw,b2:1-al*A,a0:1+al/A,a1:-2*cw,a2:1-al/A};
  });
  function magDb(f){
    let lin=1; const w=2*Math.PI*f/Fs,cw=Math.cos(w),sw=Math.sin(w),c2=Math.cos(2*w),s2=Math.sin(2*w);
    for(const q of bqs){
      const nr=Math.hypot(q.b0+q.b1*cw+q.b2*c2, -(q.b1*sw+q.b2*s2));
      const dr=Math.hypot(q.a0+q.a1*cw+q.a2*c2, -(q.a1*sw+q.a2*s2));
      lin*=nr/dr;
    }
    return 20*Math.log10(lin);
  }
  let s='';
  [20,50,100,200,500,1000,2000,5000,10000,20000].forEach(f=>{
    const x=lx(f);
    s+='<line x1="'+x+'" y1="'+m+'" x2="'+x+'" y2="'+(H-m)+'" stroke="#1c2530"/>';
    s+='<text x="'+x+'" y="'+(H-10)+'" fill="#5b6675" font-size="10" text-anchor="middle">'+(f>=1000?(f/1000)+'k':f)+'</text>';
  });
  s+='<line x1="'+m+'" y1="'+ly(0)+'" x2="'+(W-m)+'" y2="'+ly(0)+'" stroke="#33404f" stroke-dasharray="4 3"/>';
  [6,-6].forEach(g=>{ s+='<line x1="'+m+'" y1="'+ly(g)+'" x2="'+(W-m)+'" y2="'+ly(g)+'" stroke="#202b38"/>'; });
  const N=240; let d='';
  for(let i=0;i<=N;i++){
    const fr=fMin*Math.pow(fMax/fMin,i/N), g=magDb(fr);
    const x=lx(fr), y=ly(Math.max(gMin,Math.min(gMax,g)));
    d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)+' ';
  }
  s+='<path d="'+d+'" fill="none" stroke="#3fb950" stroke-width="2"/>';
  viz.innerHTML=s;
}

function genInputs(){
  return {L:+L_.value,W:+W_.value,H:+H_.value,sys:sys_.value,low:+low_.value,mid:+mid_.value,hi:+hi_.value,
    delayManual:{FL:+d_FL_.value, FR:+d_FR_.value}};
}
function redrawCanvases(){}
function pushDelay(){
  
  api('/api/apply',{gen:genInputs(),bands:currentBands}).catch(()=>{});
  showMsg(t('wrote_delay'),true);
  pendingBadge.style.display='inline';
}
function onDelayInput(){
  
  dN_FL_.value=+d_FL_.value;
  dN_FR_.value=+d_FR_.value;
  pushDelay();
}
function onDelayNumInput(){
  
  let l=Math.min(200,Math.max(0,+dN_FL_.value||0));
  let r=Math.min(200,Math.max(0,+dN_FR_.value||0));
  dN_FL_.value=l; dN_FR_.value=r;
  d_FL_.value=l; d_FR_.value=r;
  pushDelay();
}
function setStatus(on,bands){
  toggle.className="toggle "+(on?"on":"off");
  statusBands.textContent=on?t('status_on'):t('status_off');
}
function showMsg(t,ok){ msg.textContent=t; msg.style.color=ok?"var(--acc)":"#f85149"; }

const L_=document.getElementById('L'),W_=document.getElementById('W'),H_=document.getElementById('H');
const sys_=document.getElementById('sys');
const low_=document.getElementById('low'),mid_=document.getElementById('mid'),hi_=document.getElementById('hi');
const lowV=document.getElementById('lowV'),midV=document.getElementById('midV'),hiV=document.getElementById('hiV');
const d_FL_=document.getElementById('d_FL'),d_FR_=document.getElementById('d_FR');
const dN_FL_=document.getElementById('dN_FL'),dN_FR_=document.getElementById('dN_FR');
const delayCard_=document.getElementById('delayCard');
const delay51Card_=document.getElementById('delay51Card');
const viz=document.getElementById('viz');
const toggle=document.getElementById('toggle'),statusBands=document.getElementById('statusBands'),msg=document.getElementById('msg');
let currentBands=[];
let applyTimer=null;



[L_,W_,H_,sys_,low_,mid_,hi_].forEach(el=>el.addEventListener('input',()=>{
  lowV.textContent=(+low_.value).toFixed(1)+' dB';
  midV.textContent=(+mid_.value).toFixed(1)+' dB';
  hiV.textContent=(+hi_.value).toFixed(1)+' dB';
  build();
  redrawCanvases();
  if(!toggle.classList.contains('on')){ toggle.className='toggle on'; statusBands.textContent=t('status_on'); }
  api('/api/apply',{gen:genInputs(),bands:currentBands}).catch(()=>{});
  showMsg(t('wrote_curve'),true);
  pendingBadge.style.display='inline';
}));
[L_,W_,H_,sys_,low_,mid_,hi_].forEach(el=>el.addEventListener('change',()=>{ build(); redrawCanvases(); }));

function updateDelayVisibility(){
  
  const s = sys_.value;
  delayCard_.style.display = (s === 'ht20' || s === 'ht21') ? '' : 'none';
  delay51Card_.style.display = (s === 'ht51') ? '' : 'none';
}
sys_.addEventListener('input',()=>{ updateDelayVisibility(); redrawCanvases(); });
sys_.addEventListener('change',()=>{ updateDelayVisibility(); redrawCanvases(); });
[d_FL_,d_FR_].forEach(el=>el.addEventListener('input',onDelayInput));
[dN_FL_,dN_FR_].forEach(el=>el.addEventListener('change',onDelayNumInput));


let replayPolling=false;
async function pollReplayStatus(){
  if(replayPolling) return;
  replayPolling=true;
  try{
    while(true){
      const r=await (await fetch('/api/replay-status')).json();
      if(r.status==='loading'){
        replayStatus.innerHTML='<span style="color:var(--warn)">'+t('applying')+'</span>';
        await new Promise(r=>setTimeout(r,1000));
      }else if(r.status==='loaded'){
        replayStatus.innerHTML='<span style="color:var(--acc)">'+t('applied')+'</span>';
        pendingBadge.style.display='none';
        break;
      }else if(r.status==='error'){
        replayStatus.innerHTML='<span style="color:#f85149">✗ '+(r.msg||t('fail'))+'</span>';
        break;
      }else{ 
        replayStatus.textContent='';
        break;
      }
    }
  }catch(e){}
  replayPolling=false;
}



const eqWarn_=document.getElementById('eqWarn'), eqWarnMsg_=document.getElementById('eqWarnMsg');
async function pollDoubleEq(){
  try{
    const r=await (await fetch('/api/replay-status')).json();
    if(r.double_eq_advice){
      eqWarnMsg_.textContent=r.double_eq_advice;
      eqWarn_.style.display='block';
    }else{
      eqWarn_.style.display='none';
    }
  }catch(e){}
}
setInterval(pollDoubleEq, 10000);
pollDoubleEq();

async function api(path,body){
  body = body || {};
  if(typeof body === 'object' && body.lang === undefined) body.lang = currentLang;
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}
toggle.onclick=async()=>{
  if(toggle.classList.contains('on')){
    try{ const res=await api('/api/off-current',{}); setStatus(false,[]); showMsg(res.msg||t('status_off')+'，'+t('sub'),true); pollReplayStatus(); }
    catch(e){ showMsg(t('err_close')+e,false); }
  }else{
    try{
      const res=await api('/api/apply-current',{gen:genInputs(),bands:currentBands, apply:true});
      setStatus(true, res.bands||[]); showMsg(res.msg||t('save_title'),true); pollReplayStatus();
    }catch(e){ showMsg(t('err_open')+e,false); }
  }
};


const applyCurrentBtn=document.getElementById('applyCurrentBtn'), acMsg=document.getElementById('acMsg');
const replayStatus=document.getElementById('replayStatus');
const pendingBadge=document.getElementById('pendingBadge');
const langSel_=document.getElementById('lang');
applyCurrentBtn.onclick=async()=>{
  acMsg.textContent=t('proc');
  try{
    
    const r=await api('/api/replay',{});
    if(r.ok){
      acMsg.textContent='';
      pendingBadge.style.display='none';
      pollReplayStatus();
    }
    else acMsg.textContent='✗ '+(r.msg||t('fail'));
  }catch(e){ acMsg.textContent='✗ '+e; }
};

(async()=>{
  try{
    const st=await (await fetch('/api/state')).json();
    setStatus(st.on,st.bands||[]);
    const g=st.gen||{L:3.1,W:4.4,H:2.8,sys:'tv',low:0,mid:0.7,hi:1.5};
    L_.value=g.L; W_.value=g.W; H_.value=g.H; sys_.value=g.sys; updateDelayVisibility();
    low_.value=g.low; mid_.value=g.mid; hi_.value=g.hi;
    lowV.textContent=(+low_.value).toFixed(1)+' dB';
    midV.textContent=(+mid_.value).toFixed(1)+' dB';
    hiV.textContent=(+hi_.value).toFixed(1)+' dB';
    d_FL_.value=(g.delayManual && g.delayManual.FL!=null)?g.delayManual.FL:0;
    d_FR_.value=(g.delayManual && g.delayManual.FR!=null)?g.delayManual.FR:0;
    dN_FL_.value=+d_FL_.value;
    dN_FR_.value=+d_FR_.value;
    redrawCanvases();
    build();
    showMsg('',true);
    applyLang(currentLang);
  }catch(e){ showMsg(t('err_load')+e,false); }
})();
langSel_.addEventListener('change', ()=>applyLang(langSel_.value));
</script>
</body>
</html>
"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split('?')[0].rstrip('/') or '/'
        qs = self.path.split('?', 1)[1] if '?' in self.path else ''
        lang = urllib.parse.parse_qs(qs).get('lang', ['zh'])[0]
        if p in ('/', '/index.html'):
            self._send(200, HTML_PAGE, "text/html; charset=utf-8")
        elif p == '/api/state':
            on, bands = read_peq()
            self._send(200, json.dumps({"on": on, "bands": bands,
                                        "gen": read_gen(), "downmix": read_downmix(),
                                        "replayStatus": get_replay_state(lang)}))
        elif p == '/api/replay-status':
            self._send(200, json.dumps(get_replay_state(lang)))
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        p = self.path.split('?')[0].rstrip('/')
        n = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(n) if n else b'{}'
        try:
            data = json.loads(raw or b'{}')
        except Exception:
            data = {}
        if p == '/api/apply':
            
            
            bands = data.get('bands', [])
            if data.get('gen'):
                write_gen(data['gen'])
                sync_downmix_from_sys(data['gen'])
                write_delay(compute_delay_string(data['gen']))
            write_peq(bands)
            self._send(200, json.dumps({"ok": True, "on": True, "bands": bands}))
        elif p == '/api/off':
            open(PEQ_AF, 'w').write('')
            self._send(200, json.dumps({"ok": True, "on": False}))
        elif p == '/api/off-current':
            
            open(PEQ_AF, 'w').write('')
            cfg = read_jellyfin_cfg()
            lang = data.get('lang', 'zh')
            ok, m = trigger_replay(cfg, lang)
            self._send(200, json.dumps({"ok": True, "on": False,
                                        "msg": M("peq_off_ok", lang) if ok else m}))
        elif p == '/api/apply-current':
            
            bands = data.get('bands', [])
            lang = data.get('lang', 'zh')
            if data.get('gen'):
                write_gen(data['gen'])
                sync_downmix_from_sys(data['gen'])
                write_delay(compute_delay_string(data['gen']))
            if bands:
                write_peq(bands)
            cfg = read_jellyfin_cfg()
            ok, m = trigger_replay(cfg, lang)
            self._send(200, json.dumps({"ok": True,
                                        "msg": M("params_saved_ok", lang) if ok else m}))
        elif p == '/api/replay':
            
            cfg = read_jellyfin_cfg()
            lang = data.get('lang', 'zh')
            ok, m = trigger_replay(cfg, lang)
            self._send(200, json.dumps({"ok": ok, "msg": m if not ok else M("replay_triggered", lang)}))
        else:
            self._send(404, '{"error":"not found"}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"空间大师统一控制台已启动: http://0.0.0.0:{PORT}")
    print("[replay] 按钮触发模式：拖滑块只写文件不立即生效，点'保存配置'按钮才写入并生效")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
