# Core HTTP service image: text Layer A, file/metadata cleaners, and the
# optional system tools (exiftool / qpdf / c2patool) those cleaners shell out to.
#
# Build from the repository root (build context = service/):
#   docker build -f service/Dockerfile -t watermarks-remover service/
#
# Run (HTTP on loopback host port, unprivileged, read-only rootfs):
#   docker run --rm -p 127.0.0.1:8765:8765 \
#     --read-only --tmpfs /tmp \
#     watermarks-remover
#
# Any CLI stays runnable by overriding the command:
#   docker run --rm -v "$(pwd):/data" watermarks-remover \
#     /app/scripts/clean_file.py /data/notes.md -o /data/notes.cleaned.md
#
# Hardening mirrors the backend images:
#   - base image pinned by digest (no moving tag drift)
#   - c2patool pinned by release tag + sha256
#   - pip pinned (no unpinned bootstrap step)
#   - runs as an unprivileged user (a parser bug in a crafted file can no
#     longer write files as root inside the container)

ARG C2PATOOL_VERSION=c2patool-v0.27.15
ARG C2PATOOL_SHA256=7a035b727a6cdda8ad08d98fe94b3c20febee4aea4e7c1de02571b295730faf0
ARG VERSION=dev

# python:3.14-slim linux/amd64 digest.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

ARG C2PATOOL_VERSION
ARG C2PATOOL_SHA256
ARG VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libarchive-zip-perl \
        libimage-exiftool-perl \
        passwd \
        qpdf \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/c2patool.tar.gz \
        "https://github.com/contentauth/c2pa-rs/releases/download/${C2PATOOL_VERSION}/${C2PATOOL_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
    && echo "${C2PATOOL_SHA256}  /tmp/c2patool.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/c2patool.tar.gz -C /tmp \
    && install -m 0755 /tmp/c2patool/c2patool /usr/local/bin/c2patool \
    && rm -rf /tmp/c2patool /tmp/c2patool.tar.gz

COPY scripts /app/scripts

# COPY preserves the source modes, so a build host with a restrictive umask
# (e.g. 027) lands these as 0640/0750 root:root -- unreadable and untraversable
# for the unprivileged runtime user below, and the image only fails at
# container start. Normalize explicitly instead of inheriting the builder's
# umask: world-readable everywhere, execute bit for directories only (#131).
RUN chmod -R a+rX /app/scripts

RUN python3 -m pip install --no-cache-dir "pip==26.2.1"

# Unprivileged runtime user. The service only reads request bodies and writes
# to temp files / stdout, so nothing under /app needs root.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin remover
USER remover

ENV WATERMARKS_SERVER_VERSION=${VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
EXPOSE 8765
ENTRYPOINT ["python3"]
# server.py refuses a non-loopback bind with no API key set (arbitrary file
# upload/processing exposed to anyone who can reach the host) unless
# WATERMARKS_SERVER_ALLOW_INSECURE_BIND is set -- deliberately *not* set
# here. The image binds 0.0.0.0 because Docker port publishing requires it
# regardless of whether the outer `-p` maps to loopback or every interface,
# so the image cannot tell which one it is; the safe default is to refuse
# and make the caller say so. compose.yaml's wr-core service, whose actual
# access boundary *is* loopback-only (127.0.0.1:8765:8765), opts back in
# via that env var. A bare `docker run -p 8765:8765` with no API key and no
# override now refuses to start instead of silently exposing the API.
CMD ["/app/scripts/server.py", "--host", "0.0.0.0"]
