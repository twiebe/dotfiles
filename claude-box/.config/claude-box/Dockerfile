FROM node:26

ARG TZ
ENV TZ="$TZ"

ARG CLAUDE_CODE_VERSION=latest
ARG CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
ENV CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS="$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
ENV CLAUDE_CODE_FORCE_SYNC_OUTPUT=1

RUN apt-get update && apt-get install -y --no-install-recommends \
  less \
  git \
  procps \
  sudo \
  fzf \
  zsh \
  unzip \
  gnupg2 \
  gh \
  jq \
  vim \
  build-essential \
  clang \
  pkg-config \
  python3-pip \
  python3-venv \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages uv

RUN mkdir -p /usr/local/share/npm-global && \
  chown -R node:node /usr/local/share

ARG USERNAME=node

RUN mkdir /commandhistory && \
  touch /commandhistory/.bash_history && \
  chown -R $USERNAME /commandhistory

ENV DEVCONTAINER=true

RUN mkdir -p /workspace /home/node/.claude && \
  chown -R node:node /workspace /home/node/.claude

WORKDIR /workspace

ARG GIT_DELTA_VERSION=0.18.2
RUN ARCH=$(dpkg --print-architecture) && \
  wget "https://github.com/dandavison/delta/releases/download/${GIT_DELTA_VERSION}/git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  dpkg -i "git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  rm "git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb"

USER node

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV CARGO_HOME=/home/node/.cargo
ENV RUSTUP_HOME=/home/node/.rustup
ENV PATH=/home/node/.cargo/bin:$PATH:/usr/local/share/npm-global/bin
ENV SHELL=/bin/zsh
ENV EDITOR=vim
ENV VISUAL=vim
ENV COLORTERM=truecolor

ARG ZSH_IN_DOCKER_VERSION=1.2.0
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v${ZSH_IN_DOCKER_VERSION}/zsh-in-docker.sh)" -- \
  -p git \
  -p fzf \
  -a "source /usr/share/doc/fzf/examples/key-bindings.zsh" \
  -a "source /usr/share/doc/fzf/examples/completion.zsh" \
  -a "export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  -x

RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

RUN wget --https-only -qO- https://sh.rustup.rs | sh -s -- -y --no-modify-path --default-toolchain stable
RUN cargo install cbindgen
RUN cargo install just
