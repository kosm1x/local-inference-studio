# lis-web: the container a -LisWeb session runs in (operator ruling 2026-11-05: web-enabled
# sessions run in a container with no access to the operator's home folder; web access goes
# only through Jarvis's web tools over MCP). Built by scripts/web-image.ps1, which tags it
# lis-web:<the claude-code version pinned below>:
#   docker build -f container/Dockerfile --build-context jarvis=<agent-controller dir> \
#     -t lis-web:2.1.318 <this repo>
# Nothing from this repo is copied in: scripts/claude-local.ps1 bind-mounts the repo
# read-only at /lis, the Jarvis source at /jarvis/src and its tsconfig.json at
# /jarvis/tsconfig.json at run time (scripts/claude-local.ps1, -LisWeb). No ENTRYPOINT: the
# launcher passes the whole command.

# node:24-bookworm-slim, pinned by the digest docker pull reported on 2026-11-05.
FROM node:24-bookworm-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9

# python3 runs the hooks (python -I), git and curl serve the session, ca-certificates
# the TLS of npm and the Jarvis web tools. `python` is a link so `python -I` resolves.
# These four are not version-pinned: apt takes bookworm's current (security) versions,
# checked against Debian's signed index.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 git ca-certificates curl \
    && ln -s /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*

# PowerShell 7 from Microsoft's apt repo. packages-microsoft-prod.deb (Debian 12) adds the
# repo and its signing key; Microsoft publishes no checksum file for it, so the SHA-256
# below is of two downloads from the official URL on 2026-11-05 that agreed byte for byte
# (4304 bytes, Last-Modified 2023-06-16), and its MD5 matched the server's Content-MD5
# header (724c088a1651ca22e2b19d45d645104d). apt then checks every package against the
# repo's signed index. powershell is pinned to the version installed on 2026-11-05.
RUN f=packages-microsoft-prod.deb \
    && cd /tmp \
    && curl -fsSL -o "$f" "https://packages.microsoft.com/config/debian/12/$f" \
    && h=8434dcb8c346dc95fbd63dbece056c343704590b58b6a5c323d39acf52bf0b48 \
    && echo "$h  $f" | sha256sum -c - \
    && dpkg -i "$f" \
    && rm "$f" && cd / \
    && apt-get update \
    && apt-get install -y --no-install-recommends powershell=7.6.9-1.deb \
    && rm -rf /var/lib/apt/lists/*

# Claude Code, the exact version this PC runs. The tarball must match the registry's
# dist.integrity for this version (`npm view @anthropic-ai/claude-code@2.1.318
# dist.integrity` on 2026-11-05:
#   sha512-OTJgLxcvWefv8IdTsq5n90Z2IxEhLwKqHUBhwZYE4odXzKA/Tb6p2Zb5Iy9Vq7JIVcNZzn9cPxW5
#   sb42wLF95Q==
# the base64 above as hex below); a mismatch fails the build. Its native binary comes from
# the optionalDependency @anthropic-ai/claude-code-linux-x64@2.1.318, which npm checks
# against the registry's integrity only. The package's postinstall (node install.cjs) copies
# that binary over the bin/claude.exe placeholder. npm 11 runs install scripts it has no
# allowScripts entry for with only a warning, and --allow-scripts=<name> does not cover a
# tarball install, so every script is skipped (--ignore-scripts) and this one postinstall
# is run explicitly; `claude --version` below proves the installed binary runs.
RUN mkdir /tmp/cc && cd /tmp/cc \
    && npm pack @anthropic-ai/claude-code@2.1.318 \
    && h=3932602f172f59e7eff08753b2ae67f746762311212f02aa1d4061c19604e287 \
    && h=${h}57cca03f4dbea9d996f9232f55abb24855c359ce7f5c3f15b9b1be36c0b17de5 \
    && echo "$h  anthropic-ai-claude-code-2.1.318.tgz" | sha512sum -c - \
    && npm install -g --ignore-scripts ./anthropic-ai-claude-code-2.1.318.tgz \
    && cd /usr/local/lib/node_modules/@anthropic-ai/claude-code && node install.cjs \
    && cd / && rm -rf /tmp/cc && npm cache clean --force
RUN claude --version

# Jarvis's dependencies, Linux-native, from its lockfile (the `jarvis` build context is the
# agent-controller checkout; only these two files are read from it). Playwright's browser
# download is skipped: web_read falls back to a Playwright browser only on a Cloudflare
# challenge, and with no browser that path returns the tool's error, the intended outcome.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY --from=jarvis package.json package-lock.json /jarvis/
RUN cd /jarvis && npm ci && npm cache clean --force

RUN useradd --create-home --home-dir /home/lis --shell /bin/bash lis \
    && mkdir /work && chown lis:lis /work
ENV LIS_CONTAINER=1
USER lis
WORKDIR /work
