#!/bin/sh
# Container entrypoint: bring up a virtual X display for HEADFUL Chromium, then start the API.
#
# WHY a background Xvfb instead of `xvfb-run uvicorn`:
#   `xvfb-run` wraps AND GATES the whole server on the X server coming up. When it can't
#   (missing xauth, or /tmp/.X11-unix absent) it hangs or aborts BEFORE ever exec'ing uvicorn,
#   so port 7860 is never bound and the platform healthcheck sits forever at
#   "===== Application Startup =====". Here uvicorn is exec'd directly and owns PID 1; Xvfb runs
#   beside it. If X ever dies, the web server (and the port healthcheck) stays up — only
#   per-session Chromium launches would be affected, which fail loudly per-run instead of
#   silently wedging startup.
set -e

export DISPLAY="${DISPLAY:-:99}"

# Background the virtual framebuffer. `-ac` disables X access control so Chromium connects
# without an auth cookie (no xauth dance). Backgrounding means a failed/slow Xvfb never blocks
# the line below — uvicorn binds the port right away.
Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &

exec uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-7860}"
