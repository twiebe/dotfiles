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
ARG UV_VERSION=0.12.1
ARG GO_VERSION=1.26.5

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM golang:${GO_VERSION}-trixie AS go

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
#
# python3 is marked externally-managed (PEP 668), so a bare `pip3 install`
# outside a virtualenv refuses to touch the system site-packages. That is the
# intended behaviour — use `python3 -m venv` or uv above. python3-pip is here
# for use *inside* those environments, python3-venv for creating them.
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  ffmpeg \
  fzf \
  gh \
  git \
  git-lfs \
  git-delta \
  jq \
  less \
  lua5.4 \
  pkg-config \
  procps \
  python3 \
  python3-pip \
  python3-venv \
  sudo \
  tmux \
  tzdata \
  vim \
  zsh \
  && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

# Rust costs ~1.5 GB. It stays in the image anyway — a box that cannot build
# the project it is pointed at is not worth the layer it saves.
RUN apt-get update \
  && apt-get install -y --no-install-recommends rustup clang cbindgen just \
  && rm -rf /var/lib/apt/lists/*

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
RUN printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$USERNAME" > /etc/sudoers.d/$USERNAME \
  && chmod 0440 /etc/sudoers.d/$USERNAME

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
RUN rustup default stable

# ~250 MB, and above claude-code for the same cache reason as Rust.
#
# GOPATH stays at its default (/home/node/go); only its bin/ needs to be on PATH
# so that binaries from `go install` are runnable.
COPY --from=go /usr/local/go /usr/local/go
ENV PATH=/usr/local/go/bin:/home/node/go/bin:$PATH

# Last layer on purpose — it is the one that changes most often. The shell
# functions feed a concrete version in via --build-arg, so a new release
# invalidates this layer and nothing above it. That is what lets cbrecreate
# pick up a new claude-code without --no-cache.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}
