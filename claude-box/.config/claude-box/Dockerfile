# syntax=docker/dockerfile:1

# uv and Go both come out of their official images rather than an installer
# script: uv is only packaged from Debian forky/sid onwards, and trixie's Go is
# 1.24 while upstream is at 1.26 — a gap Go's own toolchain policy does not
# expect. Each gets a stage of its own because `COPY --from=` does not expand
# variables.
#
# Both version ARGs sit here, before the first FROM, because that is the only
# place a global ARG exists: the global scope ends at the first FROM, and an ARG
# after it belongs to that stage alone. Declared further down, GO_VERSION would
# expand to the empty string and the build would fail with
# `invalid reference format` on "golang:-trixie".
#
# WITH_GO is global for the same reason. Unlike the other toggles it cannot be
# a shell condition inside a RUN: Go arrives by COPY --from, and an `if` would
# have to copy the 250 MB in and delete it afterwards, which leaves it in the
# layer. The stage alias below picks an empty directory instead, so `go` names
# something either way and the COPY at the bottom needs no knowledge of it.
ARG UV_VERSION=0.12.1
ARG GO_VERSION=1.26.5
ARG WITH_GO=1

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM golang:${GO_VERSION}-trixie AS go-1
FROM node:26-trixie-slim AS go-0
RUN mkdir -p /usr/local/go
FROM go-${WITH_GO} AS go

# Debian trixie rather than Alpine: projects get built inside this container,
# and musl costs more there than Alpine's fresher packages gain. Every tool
# comes from the distro repos — no `wget | sh`, no GitHub release downloads.
# The only exceptions are claude-code (npm, the whole point of the box) plus uv
# and Go, both copied out of official images (see above).
FROM node:26-trixie-slim

# Build-time knobs default here, not in devcontainer.json: this Dockerfile is
# built directly (`docker build`) so that the image gets one fixed name instead
# of the per-workspace name the devcontainer CLI would pick. `docker build` in
# this directory therefore has to produce the intended image without arguments.
ARG TZ=Europe/Berlin
ENV TZ="$TZ"

# C.UTF-8 works without locale-gen. The previous setup exported
# LC_ALL=en_US.UTF-8 without ever generating that locale, so every invocation
# ran into "Cannot set LC_ALL to default locale". For de_DE.UTF-8, install
# `locales` and generate the locale during the build.
ENV LANG=C.UTF-8

ENV DEVCONTAINER=true
ENV CLAUDE_CODE_FORCE_SYNC_OUTPUT=1

# Base image scope: what Claude Code needs plus what building code needs.
# Anything that is per-project or personal taste (starship, direnv, language
# toolchains beyond the ones below) belongs in a project's own .devcontainer/.
# trixie versions as of this commit:
#   git-delta 0.18.2  fzf 0.60.3  gh 2.46.0  python3 3.13
#   cmake 3.31.6  curl 8.14.1  sqlite3 3.46.1
#
# python3 is marked externally-managed (PEP 668), so a bare `pip3 install`
# outside a virtualenv refuses to touch the system site-packages. That is the
# intended behaviour — use `python3 -m venv` or uv above. python3-pip is here
# for use *inside* those environments, python3-venv for creating them.
#
# Every entry below names the command that breaks without it. The three added
# most recently:
#   cmake    `cargo build` in any crate with a CMake-driven -sys dependency.
#            Not a niche case: audiopus_sys, aws-lc-sys and friends all shell
#            out to it from build.rs and fail with "is `cmake` not installed?"
#            before a single line of the crate itself compiles. The box already
#            ships build-essential, pkg-config, clang and cbindgen — cmake was
#            the one hole left in that set.
#   curl     Anything probing a local endpoint: `curl localhost:3000/health`
#            during a manual smoke test, and most upstream install snippets.
#            Missing entirely, not merely unlinked.
#   sqlite3  `sqlite3 <db> '<query>'` — checking SQL semantics by hand against
#            a dev database, which the app's own binary cannot answer.
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  cmake \
  curl \
  ffmpeg \
  fzf \
  gh \
  git \
  git-lfs \
  git-delta \
  jq \
  just \
  less \
  lua5.4 \
  pkg-config \
  procps \
  python3 \
  python3-pip \
  python3-venv \
  sqlite3 \
  sudo \
  tmux \
  tzdata \
  vim \
  zsh \
  && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

# Rust costs ~1.5 GB with its toolchain, which is why it is the first thing
# worth turning off in a box that never builds Rust. On by default: a box that
# cannot build the project it is pointed at is not worth the layer it saves.
#
# just is not here — it is a general task runner that merely ships next to Rust
# in Debian, and losing it with --without-rust would be a surprise. It sits in
# the base apt block above.
ARG WITH_RUST=1
RUN if [ "$WITH_RUST" = 1 ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends rustup clang cbindgen \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Docker-in-Docker, used by boxes started with CB_DIND=true. Only the binaries
# live here; the daemon is started per container by cb-dockerd, because the
# image has no init to run the systemd unit this package ships and because
# nothing of /var/lib/docker may end up in a layer.
#
# docker-cli is a Recommends of docker.io and would be dropped by
# --no-install-recommends; containerd, runc and iptables are hard dependencies
# and come along on their own. fuse-overlayfs is the storage driver for the
# normal case — see cb-dockerd for why overlay2 is not.
#
# docker-compose is trixie's 2.26.1, i.e. Compose v2. It installs the CLI
# plugin at /usr/libexec/docker/cli-plugins/docker-compose and symlinks
# /usr/bin/docker-compose to it, so `docker compose up` and the older
# `docker-compose up` are the same binary. Without it `docker compose` exits
# with "'compose' is not a docker command", which is what any project driving
# its dev stack from a compose file hits first.
#
# It comes from trixie main like everything else here; Docker's own apt repo is
# not needed and would break the no-third-party-repo rule at the top of this
# file. Note the name: docker-compose-v2 is a Ubuntu package and does not exist
# in Debian.
ARG WITH_DOCKER=1
RUN if [ "$WITH_DOCKER" = 1 ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends \
        docker.io \
        docker-cli \
        docker-compose \
        fuse-overlayfs \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY --chmod=0755 cb-dockerd /usr/local/bin/cb-dockerd

# Replaces zsh-in-docker, which downloaded a script from GitHub that wrote its
# own ~/.zshrc with powerlevel10k, TERM=xterm and a bash-only PROMPT_COMMAND.
# This is a small global config built from what apt installed anyway.
# /etc/zsh/zshrc is sourced BEFORE ~/.zshrc, so a shell config of your own
# inside the container overrides this without conflicting.
# Deliberately written without a single '$' so nothing gets expanded at build
# time; '<(...)' does the same job as '$(...)' when sourcing.
RUN cat >> /etc/zsh/zshrc <<'ZSHRC'

# --- claude-box ---
HISTSIZE=50000
SAVEHIST=50000
setopt hist_ignore_all_dups hist_reduce_blanks inc_append_history
unsetopt share_history

autoload -Uz compinit && compinit

command -v fzf >/dev/null && source <(fzf --zsh)

PROMPT='%F{cyan}box%f %~ %# '
ZSHRC

ARG USERNAME=node

# sudo used to be a no-op: no sudoers entry, and node has no password.
# Either do it properly or leave the package out.
#
# The env_keep line exists for cb-dockerd: postStartCommand reaches it through
# sudo, and sudo drops the environment it would otherwise read CB_DIND from.
RUN printf 'Defaults env_keep += "CB_DIND"\n%s ALL=(ALL) NOPASSWD:ALL\n' "$USERNAME" > /etc/sudoers.d/$USERNAME \
  && chmod 0440 /etc/sudoers.d/$USERNAME

# dockerd creates its socket as root:docker with mode 0660, so this membership
# is all that stands between node and "permission denied while trying to connect
# to the Docker daemon socket". groupadd -f because the docker.io package has
# usually created the group already.
RUN groupadd -f docker && usermod -aG docker "$USERNAME"

# /workspaces is only the parent — the repo is bind-mounted into
# /workspaces/<project> at runtime, and Docker creates that subdirectory itself.
RUN mkdir -p /usr/local/share/npm-global /commandhistory /workspaces /home/node/.claude \
  && chown -R $USERNAME:$USERNAME /usr/local/share/npm-global /commandhistory /workspaces /home/node/.claude

WORKDIR /workspaces
USER $USERNAME

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin
ENV SHELL=/bin/zsh
ENV EDITOR=vim
ENV VISUAL=vim
ENV COLORTERM=truecolor

# Lives on the persistent volume.
ENV HISTFILE=/commandhistory/.zsh_history

# The toolchain download happens here, as node — cbindgen and just already
# come from apt, so there is nothing to build via cargo. Deliberately ahead of
# claude-code: this layer is ~1.5 GB and must not be invalidated by a version
# bump of the layer below it.
ENV CARGO_HOME=/home/node/.cargo
ENV RUSTUP_HOME=/home/node/.rustup
ENV PATH=/home/node/.cargo/bin:$PATH
ARG WITH_RUST=1
RUN if [ "$WITH_RUST" = 1 ]; then rustup default stable; fi

# ~250 MB, and above claude-code for the same cache reason as Rust.
#
# GOPATH stays at its default (/home/node/go); only its bin/ needs to be on PATH
# so that binaries from `go install` are runnable.
COPY --from=go /usr/local/go /usr/local/go
ENV PATH=/usr/local/go/bin:/home/node/go/bin:$PATH

# sqlx-cli, for projects whose schema is managed by SQLx. Without it
# `sqlx database reset`, `sqlx migrate run` and `cargo sqlx prepare` — the
# commands behind the usual `make reset-db` and `make prepare` targets — cannot
# run at all.
#
# rustls rather than the default native-tls, which is what keeps libssl-dev out
# of the image; the rest of the default feature set is unchanged. `sqlite` is
# the bundled build, so it compiles libsqlite3 itself with the C toolchain from
# build-essential.
#
# --locked builds against the crate's own Cargo.lock, so the pin below fixes the
# whole dependency tree and not just the top-level version. 0.9.0 wants
# rustc >= 1.94, which `rustup default stable` above satisfies.
#
# The registry cache is dropped afterwards: it is ~300 MB of index and .crate
# files that go stale long before the image is rebuilt, and cargo refetches what
# a project actually needs.
#
# Above claude-code for the usual cache reason — this is a from-source build of
# several minutes and must not be redone for a claude-code release.
ARG SQLX_VERSION=0.9.0
ARG WITH_SQLX=1
RUN if [ "$WITH_SQLX" = 1 ] && [ "$WITH_RUST" = 1 ]; then \
      cargo install sqlx-cli@${SQLX_VERSION} --locked \
        --no-default-features \
        --features rustls,postgres,mysql,sqlite,completions,sqlx-toml \
      && rm -rf "$CARGO_HOME/registry" "$CARGO_HOME/git"; \
    fi

# Cargo's target directory, moved off the bind mount.
#
# /workspaces/<project> is a bind mount of the host checkout, which on macOS is
# virtiofs. Building there is slow and, worse, corrupts .rlibs. An ENV rather
# than a line in /etc/zsh/zshrc so it reaches every process — a non-interactive
# `cbexec cargo test`, a build an editor spawns, a hook — and not only
# interactive shells.
#
# One directory per box rather than per project, which is what a box already is:
# workspaceFolder in devcontainer.json is unique per repo, so a box holds one
# checkout. Not a volume, deliberately: this is rebuildable state, and
# `cb recreate` is supposed to hand back a clean slate.
#
# Must stay BELOW the `cargo install` above, otherwise that build's
# intermediates land here and ship inside the image.
ENV CARGO_TARGET_DIR=/home/node/.cache/cargo-target

# Playwright's Chromium plus the shared libraries it dlopen()s at startup.
# Without the libraries `npx playwright install chromium` refuses to run at all,
# failing inside _validateHostRequirements; without the browser every Playwright
# test aborts with "Executable doesn't exist at .../chrome-linux/headless_shell".
# The two steps together cost several minutes on a cold cache, which is the
# whole reason to bake them in.
#
# install-deps is the only half that needs root, since it apt-installs. The
# download runs as node so the browser lands in /home/node/.cache/ms-playwright,
# an ordinary image layer — none of the volumes in devcontainer.json cover
# ~/.cache. Order matters: the host-requirements check runs first.
#
# The `apt-get update` is not redundant. install-deps shells out to `apt-get
# install` without refreshing first, and every apt block above ends by wiping
# /var/lib/apt/lists — so without this the build dies on "Unable to locate
# package libnss3" for two dozen packages that trixie does in fact carry.
#
# check-images: hold - this pin deliberately does not track any project's
# lockfile. A project pins @playwright/test in its own package-lock.json and
# this image is shared by all of them, so the two are independent by
# construction. The baked browser is a warm cache, not a contract: a project on
# another version runs `npx playwright install chromium` and gets its own
# revision beside this one, because the cache directory is node-owned. Bump this
# on its own schedule.
ARG PLAYWRIGHT_VERSION=1.62.1
ARG WITH_PLAYWRIGHT=1
RUN if [ "$WITH_PLAYWRIGHT" = 1 ]; then \
      sudo apt-get update \
      && sudo npx --yes @playwright/test@${PLAYWRIGHT_VERSION} install-deps chromium \
      && npx --yes @playwright/test@${PLAYWRIGHT_VERSION} install chromium \
      && sudo rm -rf /var/lib/apt/lists/* /root/.npm \
      && rm -rf /home/node/.npm/_npx; \
    fi

# Last layer on purpose — it is the one that changes most often. cb feeds a
# concrete version in via --build-arg, so a new release
# invalidates this layer and nothing above it. That is what lets `cb recreate`
# pick up a new claude-code without --no-cache.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# What this image was actually built with, so `docker inspect` can answer it.
# cb reads this label rather than its own state file: the file only remembers
# what to build next time and may be lost or hand-edited, while the label
# travels with the image it describes.
#
# Last instruction on purpose — a LABEL is metadata and rebuilding it costs
# nothing, so it must not sit above the claude-code layer that changes most
# often.
ARG WITH_GO
LABEL cb.features="docker=${WITH_DOCKER},go=${WITH_GO},playwright=${WITH_PLAYWRIGHT},rust=${WITH_RUST},sqlx=${WITH_SQLX}"
