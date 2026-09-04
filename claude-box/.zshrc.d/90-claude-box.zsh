CB_DIR="$HOME/.config/claude-box"
CB_CONFIG="$CB_DIR/devcontainer.json"

# Must match the "image" field in $CB_CONFIG.
CB_IMAGE="claude-box:latest"

# Directories a box may be started in. Everything else is refused unless
# --force is passed; see _cb_gate.
CB_ROOTS=("$HOME/git" "$HOME/tmp")

# A project's own .devcontainer/ always wins; the global config is the fallback.
_cb_local_config() {
  [ -f .devcontainer/devcontainer.json ]
}

# Project slug, used for both the container name and the workspace path inside
# the box. Only [a-z0-9-] survives, which keeps --name and --hostname happy
# (underscores and dots are fine for a container name but not for a hostname).
#
# After substituting the leftovers, runs of dashes collapse and the edges get
# trimmed, otherwise a dotted directory name reads badly: ~/.dotfiles would
# become cb--dotfiles and /workspaces/-dotfiles. A name made up entirely of
# discarded characters falls back to "box".
_cb_project() {
  setopt local_options extended_glob
  local base="${${PWD:t}//[^a-zA-Z0-9-]/-}"
  base="${${${base//-##/-}##-}%%-}"
  printf '%s' "${${base:-box}:l}"
}

# Short digest of the absolute path, to tell two checkouts of the same directory
# name apart. shasum ships with macOS, sha256sum with coreutils.
_cb_path_hash() {
  local hash
  if command -v shasum >/dev/null 2>&1; then
    hash="$(printf '%s' "$PWD" | shasum -a 256)"
  else
    hash="$(printf '%s' "$PWD" | sha256sum)"
  fi
  printf '%s' "${hash[1,8]}"
}

# Every devcontainer call has to agree on the config, because the CLI finds an
# existing container by labels that include the config path. Mixing them would
# start a second container for the same folder.
#
# CB_PROJECT and CB_NAME are exported for the duration of the call only;
# devcontainer.json reads them via ${localEnv:...}. They live here rather than in
# the JSON because the only variable the CLI offers,
# ${localWorkspaceFolderBasename}, is neither sanitized nor unique.
_cb_dc() {
  local cmd="$1"
  shift
  local -x CB_PROJECT="$(_cb_project)"
  local -x CB_NAME="cb-$CB_PROJECT-$(_cb_path_hash)"
  local -x CB_DIND="${CB_DIND:-false}"
  if _cb_local_config; then
    devcontainer "$cmd" --workspace-folder "$PWD" "$@"
  else
    devcontainer "$cmd" --workspace-folder "$PWD" --config "$CB_CONFIG" "$@"
  fi
}

# Newest published claude-code version, handed to the build as a concrete
# value.
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

# The global image, built by hand and shared by every repo.
#
# `devcontainer up` cannot do this: it derives the image name from the
# workspace folder path, so each repo ends up with its own vsc-<folder>-<hash>
# image even when the config is identical. Building here and referencing the
# fixed tag from devcontainer.json keeps it to one image.
#
# All other build args default inside the Dockerfile; only the version needs to
# be resolved at call time. Extra args are passed through (e.g. --no-cache).
_cb_build() {
  docker build "$@" \
    --build-arg CLAUDE_CODE_VERSION="$(_cb_claude_version)" \
    --tag "$CB_IMAGE" \
    "$CB_DIR"
}

# Build only what is missing: the image has to exist before a container can run,
# but keeping it current is cbupdate's job, not something every `cb` pays for.
#
# `cb` runs many times a day and almost always on a warm cache, where a build is
# pure overhead: an `npm view` round trip for the version plus a second of Docker
# walking the layers, and 20 lines of "CACHED" that read like a rebuild.
#
# Building is a no-op for a project with its own .devcontainer/ — that one brings
# its own image and the CLI builds it as part of `up`.
_cb_ensure_image() {
  _cb_local_config && return 0
  docker image inspect "$CB_IMAGE" >/dev/null 2>&1 || _cb_build "$@"
}

# Is the current directory inside one of CB_ROOTS?
#
# Compares resolved paths, so a symlinked ~/git — or a cd through one — still
# counts. A root that does not exist simply never matches.
_cb_in_roots() {
  local here="${PWD:A}" root
  for root in $CB_ROOTS; do
    root="${root:A}"
    [[ "$here" == "$root" || "$here" == "$root"/* ]] && return 0
  done
  return 1
}

# The directory gate, in front of every command that starts or replaces a box.
#
# A box bind-mounts the directory it is launched from and hands it to an agent
# with permissions loosened, so starting one in the wrong place — $HOME, /, a
# directory reached by a stray cd — is the expensive mistake. Checkouts live in
# ~/git and scratch work in ~/tmp; anything else is a typo until said otherwise.
#
# --force says otherwise. It is consumed here rather than passed on, wherever in
# the arguments it appears, and the rest is left in the caller's `cb_argv` for
# the flag parsing that follows — `cb` forwards its arguments to claude, which
# has no idea what --force means.
#
# The answer travels as CB_FORCE, the way --dind travels as CB_DIND: `cb`
# gates once and cbup, called a line later, sees the decision through the
# caller's `local CB_FORCE`. So `CB_FORCE=true cb` works too.
_cb_gate() {
  local -a rest
  local arg
  for arg in "$@"; do
    [[ "$arg" == --force ]] && { CB_FORCE=true; continue }
    rest+=("$arg")
  done
  cb_argv=("${rest[@]}")

  [[ "$CB_FORCE" == true ]] && return 0
  _cb_in_roots && return 0

  print -u2 "refusing to start a claude box in $PWD"
  print -u2 "boxes belong under ${(j: or :)CB_ROOTS} — pass --force to override"
  return 1
}

# --dind asks for a box with its own Docker daemon: containers built inside it
# see the same paths the box does, so a bind mount of the workspace resolves.
# Costs --privileged, which is why it is not the default.
#
# Offered by every command that replaces the container, and by no other, because
# --privileged is a creation-time flag: cbup would accept it and then silently
# do nothing whenever a container is already there.
#
# Only needed once per box. CB_DIND ends up in the container's environment, so a
# later plain `cb` brings the daemon back up; recreating without the flag, on the
# other hand, gives back an ordinary box.
#
# The answer travels as CB_DIND, which _cb_dc exports and devcontainer.json turns
# into --privileged. Assigns into the caller's `local CB_DIND` via zsh's dynamic
# scoping; `CB_DIND=true cbrecreate` still works and is what the flag expands to.
# An unknown argument is rejected rather than ignored, so a typo cannot quietly
# hand back an unprivileged box.
_cb_dind() {
  case "${1:-}" in
    --dind) CB_DIND=true ;;
    "") ;;
    *) print -u2 "unknown option: $1"; return 1 ;;
  esac
}

# Starts the box, creating it only if it is not there yet. Deliberately does not
# take --dind: it would be a no-op against a container that already exists, and
# a silently unprivileged box is the failure this whole flag exists to avoid.
cbup() {
  local CB_FORCE="${CB_FORCE:-false}"
  local -a cb_argv
  _cb_gate "$@" || return
  if [[ "${cb_argv[1]:-}" == --dind ]]; then
    print -u2 "cbup does not take --dind — --privileged applies at creation time only."
    print -u2 "use: cbrecreate --dind"
    return 1
  fi
  _cb_ensure_image && _cb_dc up
}

cbexec() {
  _cb_dc exec -- "$@"
}

# Container only: throw it away and start a fresh one from the image that is
# already there — for picking up changed mounts, env or volumes. The image is
# left exactly as it is; use cbupdate or cbrebuild to touch that.
#
# The volumes are untouched as always; whatever the old box had in /workspaces
# beyond the bind mount is gone. Takes --dind (see _cb_dind).
cbrecreate() {
  local CB_DIND="${CB_DIND:-false}" CB_FORCE="${CB_FORCE:-false}"
  local -a cb_argv
  _cb_gate "$@" || return
  _cb_dind "${cb_argv[@]}" || return
  _cb_ensure_image && _cb_dc up --remove-existing-container
}

# Pull in a new claude-code release, then recreate the container so it actually
# runs the new binary.
#
# Cheap on purpose: the build keeps its cache, so a bump only invalidates the
# npm layer at the very bottom of the Dockerfile — the Rust toolchain above it
# stays. When the version is unchanged, every layer is a cache hit and this is
# just cbrecreate with a `npm view` in front of it.
#
# For a project-local .devcontainer/ there is nothing to resolve here; the CLI
# builds that image itself, from its own Dockerfile.
#
# Takes --dind (see _cb_dind).
cbupdate() {
  local CB_DIND="${CB_DIND:-false}" CB_FORCE="${CB_FORCE:-false}"
  local -a cb_argv
  _cb_gate "$@" || return
  _cb_dind "${cb_argv[@]}" || return
  _cb_local_config || _cb_build || return
  _cb_dc up --remove-existing-container
}

# Nuclear option: discard every cached layer, Rust toolchain included, then
# recreate the container. Reach for cbupdate first — it gets you a current
# claude-code without the ~1.5 GB Rust download, the from-source sqlx-cli build
# and the Playwright browser download.
#
# The two branches differ because a project-local .devcontainer/ is built by the
# CLI, which spells the flag --build-no-cache.
#
# Takes --dind (see _cb_dind).
cbrebuild() {
  local CB_DIND="${CB_DIND:-false}" CB_FORCE="${CB_FORCE:-false}"
  local -a cb_argv
  _cb_gate "$@" || return
  _cb_dind "${cb_argv[@]}" || return
  if _cb_local_config; then
    _cb_dc up --remove-existing-container --build-no-cache
  else
    _cb_build --no-cache && _cb_dc up --remove-existing-container
  fi
}

# The devcontainer CLI stamps every container it starts with the host folder it
# was launched from and with the config that produced it, and it finds an
# existing container again by exactly those labels. Matching on them beats
# matching on the name: a project with its own .devcontainer/ never reads
# CB_NAME, so its container ends up with whatever Docker made up.
#
# `-a` rather than plain `ps`, so an already stopped container is found too.
_cb_names() {
  docker ps -a --format '{{.Names}}' "$@"
}

# Same set, as a table. The folder column is what actually identifies a box; the
# name only carries the project slug and a hash.
_cb_table() {
  docker ps -a "$@" \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Label "devcontainer.local_folder"}}'
}

# Remove whatever the filter matches, and report it by name.
#
# No -v anywhere in this file: cb-history-<id> holds the shell history and a
# teardown must never take it along. The Claude config, which is the expensive
# half of coming back, is a bind mount of the host's ~/.claude and is out of
# reach of -v either way. Only container state is lost.
_cb_rm() {
  local -a names
  names=(${(f)"$(_cb_names "$@")"})
  names=(${names:#})
  (( $#names )) || return 1
  docker rm -f $names >/dev/null || return
  print "removed: ${(j: :)names}"
}

# Throw the box for this directory away. The counterpart to cbup: cbrecreate is
# "start over right now", this one is "I am done here".
#
# --all covers every box running off the global config. A project with its own
# .devcontainer/ carries a different config_file label and is by then
# indistinguishable from any other devcontainer, so that one is dcdown's job —
# plain cbdown still gets it, being keyed on the folder.
cbdown() {
  if [[ "$1" == (-a|--all) ]]; then
    _cb_rm --filter "label=devcontainer.config_file=$CB_CONFIG" && return
    print -u2 "no claude box found"
    return 1
  fi
  _cb_rm --filter "label=devcontainer.local_folder=$PWD" && return
  print -u2 "no claude box for $PWD"
  return 1
}

cbls() {
  _cb_table --filter "label=devcontainer.config_file=$CB_CONFIG"
}

# Every devcontainer on the machine, whatever started it. The label is queried
# for existence only, so VS Code's containers and other projects' `devcontainer
# up` are in scope as well — hence the listing and the prompt before anything
# happens. -y skips the prompt for scripted use.
dcdown() {
  local -a names
  names=(${(f)"$(_cb_names --filter "label=devcontainer.local_folder")"})
  names=(${names:#})
  (( $#names )) || { print -u2 "no devcontainer found"; return 1 }

  if [[ "$1" != (-y|--yes) ]]; then
    dcls
    print
    read -q "?remove $#names devcontainer(s)? [y/N] " || { print; return 1 }
    print
  fi

  docker rm -f $names >/dev/null || return
  print "removed: ${(j: :)names}"
}

dcls() {
  _cb_table --filter "label=devcontainer.local_folder"
}

# Gates before cbup rather than leaving it to cbup, because --force has to be
# stripped here: everything else on the line belongs to claude.
claude-box() {
  local CB_FORCE="${CB_FORCE:-false}"
  local -a cb_argv
  _cb_gate "$@" || return
  cbup >/dev/null && cbexec claude "${cb_argv[@]}"
}

alias cb='claude-box'
alias cbc='claude-box --continue'
