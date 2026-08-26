FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Switch to Yandex Debian mirror (RU) — Fastly CDN drops connections on large packages
# from RU networks. Yandex mirror is geographically close and stable.
# Also configure apt with aggressive retries and longer timeouts so transient drops
# don't kill the whole build.
RUN set -eux; \
    sed -i 's|http://deb.debian.org/debian|http://mirror.yandex.ru/debian|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|http://deb.debian.org/debian|http://mirror.yandex.ru/debian|g' /etc/apt/sources.list 2>/dev/null || true; \
    sed -i 's|http://deb.debian.org/debian-security|http://mirror.yandex.ru/debian-security|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|http://deb.debian.org/debian-security|http://mirror.yandex.ru/debian-security|g' /etc/apt/sources.list 2>/dev/null || true; \
    sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's/ main$/ main contrib/' /etc/apt/sources.list 2>/dev/null || true; \
    printf 'Acquire::Retries "10";\nAcquire::http::Timeout "120";\nAcquire::https::Timeout "120";\nAcquire::http::No-Cache "true";\nAcquire::Queue-Mode "access";\n' > /etc/apt/apt.conf.d/80-retries

# LibreOffice + comprehensive font set so PPTX rendering preserves Cyrillic and
# common display typefaces (Calibri/Arial/Times → Liberation/Carlito substitutes).
# Cache mounts: partial .deb downloads survive between build attempts so a dropped
# connection doesn't force re-downloading everything.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        libreoffice \
        libreoffice-l10n-ru \
        libreoffice-impress \
        fonts-liberation \
        fonts-liberation2 \
        fonts-dejavu \
        fonts-dejavu-extra \
        fonts-noto \
        fonts-noto-core \
        fonts-noto-color-emoji \
        fonts-freefont-ttf \
        fonts-croscore \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fontconfig \
        ffmpeg \
        poppler-utils \
        wget \
        cabextract && \
    fc-cache -fv && \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
        | debconf-set-selections && \
    apt-get install -y --no-install-recommends ttf-mscorefonts-installer || true && \
    fc-cache -f -v

RUN groupadd -g 1000 appgroup && useradd -u 1000 -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt && \
    pip install -r requirements-dev.txt

# ── Custom .ttf fonts ─────────────────────────────────────────────────────
# Typefaces real uploaded decks ask for that Debian does not package. A family
# LibreOffice cannot resolve is silently substituted, and the substitute's
# metrics reflow the text — so shipping the real thing is a rendering-fidelity
# fix, not cosmetics. Static instances only: LibreOffice renders a *variable*
# font at its first named instance (Montserrat → Thin, Merriweather → Light),
# which is worse than the substitution it replaces. See docs/DECISIONS.md §56.
#
# Placed after pip install and before "COPY . ." so adding a font does not
# invalidate the pip layer cache.
COPY ./fonts/*.ttf /usr/local/share/fonts/
RUN fc-cache -f

COPY --chown=appuser:appgroup lo-emoji-substitution.xcu /app/lo-emoji-substitution.xcu

COPY --chown=appuser:appgroup . .

# Drop root. `appuser` (uid/gid 1000) must own everything the app writes at
# runtime: /app/storage (generated PPTX/PNG/WAV/MP4 + the per-run LibreOffice
# UserInstallation profile `_lo_profile`) and /app itself, which is $HOME for
# appuser and the pytest/coverage rootdir in dev. WORKDIR created /app as root,
# so hand it over explicitly — a non-recursive chown keeps the layer tiny while
# COPY --chown above already placed the copied tree correctly.
# In prod /app/storage is what Docker seeds the `app_storage` named volume from
# on first mount, so this ownership is what the volume inherits.
RUN mkdir -p /app/storage && chown appuser:appgroup /app /app/storage

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
