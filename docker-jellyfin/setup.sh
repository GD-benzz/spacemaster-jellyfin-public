#!/bin/bash
set -e
FFDIR=/usr/lib/jellyfin-ffmpeg
FF="$FFDIR/ffmpeg"
FF_ORIG="$FFDIR/ffmpeg.orig"
WRAP=/opt/sm/sm_wrapper.sh
LOG=/opt/sm/wrapper.log
if [ -f "$WRAP" ]; then
  if [ -f "$FF" ] && [ ! -f "$FF_ORIG" ]; then
    mv "$FF" "$FF_ORIG"
  fi
  cp "$WRAP" "$FF"
  chmod +x "$FF"
  echo "$(date '+%F %T') setup: ffmpeg wrapped by spacemaster" >> "$LOG"
else
  if [ ! -f "$FF" ] && [ -f "$FF_ORIG" ]; then
    mv "$FF_ORIG" "$FF"
  fi
  echo "$(date '+%F %T') setup: wrapper missing at $WRAP, running stock Jellyfin" >> "$LOG"
fi
exec /jellyfin/jellyfin "$@"