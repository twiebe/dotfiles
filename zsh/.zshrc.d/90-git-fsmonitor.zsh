# git fsmonitor
#
# The builtin daemon replaces the per-file lstat scan of `git status` with a
# query against a process subscribed to FSEvents. Worth it on large worktrees,
# pointless on small ones — and not free to leave running: one daemon per repo,
# no idle timeout, and the health thread that would shut it down is an empty
# stub on macOS. Hence opt-in per repo, plus a killall.
#
# core.fsmonitor lives in .git/config, which is untracked and does not survive a
# fresh clone. For a durable rule use includeIf in ~/.config/git/config.

zmodload -F zsh/datetime p:EPOCHREALTIME

# Milliseconds for one full status scan.
_git_fsmonitor_time_status() {
  local start=$EPOCHREALTIME
  command git status --porcelain=2 >/dev/null 2>&1
  printf '%.0f' $(( (EPOCHREALTIME - start) * 1000 ))
}

_git_fsmonitor_guard() {
  if ! command git rev-parse --show-toplevel >/dev/null 2>&1; then
    print -u2 "git-fsmonitor: not inside a git worktree"
    return 1
  fi

  # The exit code cannot tell "unsupported platform" from "not running", so
  # match the message. On Linux, including every devcontainer, setting
  # core.fsmonitor is silently inert — worse than refusing.
  if [[ "$(command git fsmonitor--daemon status 2>&1)" == *"not supported on this platform"* ]]; then
    print -u2 "git-fsmonitor: builtin daemon not supported on this platform"
    return 1
  fi

  return 0
}

git-fsmonitor-enable() {
  _git_fsmonitor_guard || return 1

  local root before after tracked
  root="$(command git rev-parse --show-toplevel)"

  if [[ "$(command git config --get core.fsmonitor)" == "true" ]]; then
    print "git-fsmonitor: already enabled for ${root}"
    return 0
  fi

  before=$(_git_fsmonitor_time_status)

  command git config core.fsmonitor true || return 1

  # The first status starts the daemon and still pays for a full scan while it
  # builds its state, so warm it before measuring.
  command git status --porcelain=2 >/dev/null 2>&1
  after=$(_git_fsmonitor_time_status)

  tracked="$(command git ls-files | wc -l | tr -d ' ')"

  print "git-fsmonitor: enabled for ${root}"
  print "  tracked files  ${tracked}"
  print "  git status     ${before}ms -> ${after}ms"

  # Separate switch, cheap to leave on — point at it rather than enabling it
  # behind the user's back.
  if [[ "$(command git config --get feature.manyFiles)" != "true" ]]; then
    print "  hint           feature.manyFiles is off; it cuts the untracked scan and index I/O too"
  fi
}

git-fsmonitor-disable() {
  _git_fsmonitor_guard || return 1

  local root after
  root="$(command git rev-parse --show-toplevel)"

  # Explicit false so this also beats a global or includeIf rule. Use
  # `git config --unset core.fsmonitor` to fall back to the global default.
  command git config core.fsmonitor false || return 1

  # Otherwise the daemon for this worktree keeps running unqueried.
  command git fsmonitor--daemon stop >/dev/null 2>&1

  after=$(_git_fsmonitor_time_status)

  print "git-fsmonitor: disabled for ${root}"
  print "  git status     ${after}ms"
}

git-fsmonitor-killall() {
  local -a pids

  # git spawns it as `<git> fsmonitor--daemon run --detach --ipc-threads=N`.
  # The anchor matters: an unanchored -f also matches any shell, editor or grep
  # that merely mentions the string — including the one running this.
  pids=(${(f)"$(pgrep -f '^[^ ]*git fsmonitor--daemon run' 2>/dev/null)"})
  pids=(${pids:#$$})

  if (( ${#pids} == 0 )); then
    print "git-fsmonitor: no daemons running"
    return 0
  fi

  print "git-fsmonitor: stopping ${#pids} daemon(s)"
  command ps -o pid=,rss=,command= -p ${(j:,:)pids} 2>/dev/null

  # Safe: the next git command in an affected repo rescans once and respawns.
  # core.fsmonitor is left alone, so the repos stay enabled.
  kill ${pids} 2>/dev/null

  print "git-fsmonitor: sent SIGTERM; repos stay enabled and respawn on next use"
}
