CB_DEFAULT="$HOME/.config/claude-box/devcontainer.json"

_cb_config_arg() {
  [ -f .devcontainer/devcontainer.json ] && echo "" || echo "--config $CB_DEFAULT"
}

# Newest published claude-code version, handed to the build as a concrete
# value. The default devcontainer.json picks it up via
# ${localEnv:CLAUDE_CODE_VERSION:latest}.
#
# "latest" would be useless here: Docker caches a RUN layer by its instruction
# text, not by what the tag resolved to, so `npm install ...@latest` stays
# frozen forever. A concrete version changes the text exactly when a release
# happens.
#
# Falls back to "latest" when npm is missing or the registry is unreachable,
# which simply leaves the layer cached — same behaviour as before.
_cb_claude_version() {
  command -v npm >/dev/null 2>&1 || { echo latest; return }
  npm view @anthropic-ai/claude-code version --fetch-timeout=3000 2>/dev/null || echo latest
}

# Single entry point for every variant, so all of them pass the same build arg
# and therefore produce the same cache key. Handing "latest" to one command and
# a pinned version to another would flip that key back and forth and rebuild
# the claude-code layer on every switch.
#
# `local -x` exports the version for the duration of this call only.
_cb_up() {
  local -x CLAUDE_CODE_VERSION="$(_cb_claude_version)"
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_cb_config_arg) "$@"
}

cbup() {
  _cb_up
}

cbexec() {
  eval devcontainer exec --workspace-folder "\"$PWD\"" $(_cb_config_arg) -- "$@"
}

# Throw the container away and start a fresh one — for picking up changed
# mounts, env or volumes.
#
# `devcontainer up` always re-evaluates the Dockerfile on the way there, so the
# image is reconsidered too. Every layer comes from the cache except when a new
# claude-code release exists, in which case only its layer is rebuilt; the Rust
# toolchain above it stays cached. A container-only recreate is not something
# the CLI offers.
cbrecreate() {
  _cb_up --remove-existing-container
}

# Nuclear option: discard every cached layer, Rust toolchain included, then
# recreate the container. Reach for cbrecreate first.
cbrebuild() {
  _cb_up --remove-existing-container --build-no-cache
}

claude-box() {
  cbup >/dev/null && cbexec claude "$@"
}

alias cb='claude-box'
alias cbc='claude-box --continue'
