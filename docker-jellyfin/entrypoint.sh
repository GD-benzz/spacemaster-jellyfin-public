#!/bin/sh
set -e
SRC=/opt/sm-dist
DST=/opt/sm
mkdir -p "$DST"
for f in sm_dsp_engine sm_wrapper.sh setup.sh peq_toggle_nas.py engine_runtime.py profile-proxy.py; do
  cp -f "$SRC/$f" "$DST/$f" 2>/dev/null || true
done
chmod +x "$DST/sm_dsp_engine" "$DST/sm_wrapper.sh" "$DST/setup.sh" 2>/dev/null || true

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
case "${SM_ROLE:-console}" in
  proxy)
    exec python3 /opt/sm/profile-proxy.py
    ;;
  *)
    exec python3 /opt/sm/peq_toggle_nas.py
    ;;
esac
