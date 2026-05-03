# syntax=docker/dockerfile:1.7
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
        fonts-freefont-ttf \
        fonts-croscore \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fontconfig \
        ffmpeg \
        poppler-utils \
        wget && \
    fc-cache -fv

RUN groupadd -g 1000 appgroup && useradd -u 1000 -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
