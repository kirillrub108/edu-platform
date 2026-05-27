#!/bin/sh
set -e

# When docker-compose bind-mounts the host's frontend/node_modules onto /app/node_modules,
# the host directory may be empty on first run and would shadow the modules baked into the
# image. Detect that case and seed the bind mount from the snapshot we kept at build time.
# After this, VS Code on the host has a real node_modules to read for TypeScript while the
# container uses the same files.
BAKED_PLATFORM=$(cat /opt/node_modules_baked/.platform 2>/dev/null || echo "unknown")
INSTALLED_PLATFORM=$(cat /app/node_modules/.platform 2>/dev/null || echo "none")

if [ ! -d /app/node_modules/nuxt ] || [ "$INSTALLED_PLATFORM" != "$BAKED_PLATFORM" ]; then
  echo "[entrypoint] Seeding /app/node_modules from baked snapshot (platform: $BAKED_PLATFORM)..."
  cp -a /opt/node_modules_baked/. /app/node_modules/
  echo "[entrypoint] Done."
fi

exec "$@"
