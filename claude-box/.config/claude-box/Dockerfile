# syntax=docker/dockerfile:1

# uv is only packaged from Debian forky/sid onwards. Instead of running an
# installer script, pull it from the official, pinnable image — plain file
# copying. It needs its own stage because `COPY --from=` does not expand
# variables, which in turn requires the ARG to live in the global scope,
# i.e. before the first FROM.
ARG UV_VERSION=0.12
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Debian trixie rather than Alpine: projects get built inside this container,
# and musl costs more there than Alpine's fresher packages gain. Every tool
# comes from the distro repos — no `wget | sh`, no GitHub release downloads.
# The only exceptions are claude-code (npm, the whole point of the box) and
# uv (see above).
FROM node:26-trixie-slim

ARG TZ
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
#   git-delta 0.18.2  fzf 0.60.3  gh 2.46.0
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  fzf \
  gh \
  git \
  git-delta \
  jq \
  less \
  pkg-config \
  procps \
  sudo \
  tmux \
  tzdata \
  vim \
  zsh \
  && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

# Rust costs ~1.5 GB, so it is a switch rather than a fixed part of the image.
# Turn it off for a lean box with --build-arg WITH_RUST=0.
ARG WITH_RUST=1
RUN if [ "$WITH_RUST" = "1" ]; then \
  apt-get update \
  && apt-get install -y --no-install-recommends rustup clang cbindgen just \
  && rm -rf /var/lib/apt/lists/*; \
  fi

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

RUN mkdir -p /usr/local/share/npm-global /commandhistory /workspace /home/node/.claude \
  && chown -R $USERNAME:$USERNAME /usr/local/share/npm-global /commandhistory /workspace /home/node/.claude

WORKDIR /workspace
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
RUN if [ "$WITH_RUST" = "1" ]; then rustup default stable; fi

# Last layer on purpose — it is the one that changes most often. The default
# devcontainer.json feeds a concrete version in via
# ${localEnv:CLAUDE_CODE_VERSION:latest}, so a new release invalidates this
# layer and nothing above it. That is what lets cbrecreate pick up a new
# claude-code without --build-no-cache.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}
