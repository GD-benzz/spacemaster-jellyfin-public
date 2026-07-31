import os
import sys
import json
import subprocess
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_CANDIDATES = [
    os.path.join(_HERE, "sm_dsp_engine"),
    "/opt/sm/sm_dsp_engine",
    "/usr/local/bin/sm_dsp_engine",
]
def _engine():
    for cand in _ENGINE_CANDIDATES:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return "bin", cand
    try:
        import engine_core
        return "py", engine_core
    except Exception:
        return None, None
def compute(gen):
    g = dict(gen) if gen else {}
    if g.get('sys') == 'ht20':
        g['sys'] = 'ht21'
    kind, eng = _engine()
    if kind == "bin":
        out = subprocess.run([eng, "compute", json.dumps(g, ensure_ascii=False)],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    if kind == "py":
        return eng.compute(g)
    raise RuntimeError("空间大师算法引擎未找到：需 sm_dsp_engine 二进制或 engine_core 模块")
def auto_baseline(gen):
    kind, eng = _engine()
    if kind == "py":
        return eng.auto_baseline(gen)
    if kind == "bin":
        out = subprocess.run([eng, "auto-baseline", json.dumps(gen, ensure_ascii=False)],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    return {}
def build_filter(params):
    kind, eng = _engine()
    if kind == "bin":
        out = subprocess.run([eng, "build-filter", json.dumps(params, ensure_ascii=False)],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    if kind == "py":
        return eng.build_filter_string(params)
    raise RuntimeError("空间大师算法引擎未找到")
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "compute":
        print(json.dumps(compute(json.loads(sys.argv[2])), ensure_ascii=False, indent=2))