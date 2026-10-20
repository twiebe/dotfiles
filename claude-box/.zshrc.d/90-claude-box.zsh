# claude-box lives in ~/.local/bin/cb, which 99-path.zsh already puts on PATH.
# What is left here is what a shell function is still better at than a Python
# script: completion, and one alias for the invocation used most.

alias cbc='cb --continue'

# Completes cb's own subcommands and flags. Anything cb forwards to claude is
# out of scope — claude ships no zsh completion and guessing at its flags here
# would go stale on its next release.
_cb() {
  local -a subcommands features
  subcommands=(
    'run:start a fresh box and run claude in it'
    'shell:a fresh box with zsh'
    'exec:run a command in a running box'
    'ls:list running boxes'
    'mount:remember extra mounts for this directory'
    'rebuild-image:rebuild the shared image'
    'update-claude:rebuild with the newest claude-code'
    'config:show or set this box'"'"'s settings'
    'image-config:show or set the image'"'"'s toolchains'
    'volume:prune the volumes cb keeps'
    'enable:let boxes start in a directory and below it'
    'disable:keep boxes out of a directory and below it'
    'untag:remove a directory'"'"'s tag again'
    'enabled:whether a box may start in a directory'
  )
  features=(docker ffmpeg go kubernetes pandoc playwright-deps python rust sqlx tofu)

  if (( CURRENT == 2 )); then
    _describe -t commands 'cb command' subcommands
    _values 'option' '--docker' '--no-docker' '--force' '--dry-run' '--help' \
      '-v' '--volume'
    return
  fi

  case "${words[2]}" in
    ls|disable|untag|enabled) (( CURRENT == 3 )) && _directories ;;
    enable)
      if (( CURRENT == 3 )); then
        _values 'mode' 'all' 'git'
      elif (( CURRENT == 4 )); then
        _directories
      fi
      ;;
    exec)
      if (( CURRENT == 3 )); then
        _values 'option' '-n'
      elif [[ "${words[3]}" == -n && CURRENT == 4 ]]; then
        local -a boxes
        boxes=(${(f)"$(docker ps --filter label=cb.box --format '{{.Names}}' 2>/dev/null)"})
        _values 'box' $boxes
      fi
      ;;
    mount)
      if (( CURRENT == 3 )); then
        _values 'action' 'add' 'rm' 'ls'
      elif [[ "${words[3]}" == add ]]; then
        _directories
      fi
      ;;
    rebuild-image)
      _values 'option' '--no-cache' \
        ${^features/#/--with-} ${^features/#/--without-}
      ;;
    config) _values 'setting' 'docker' 'force' '--prune' ;;
    image-config)
      if (( CURRENT == 3 )); then
        _values 'feature' $features
      elif (( CURRENT == 4 )); then
        _values 'value' 'true' 'false'
      fi
      ;;
    volume)
      if (( CURRENT == 3 )); then
        _values 'action' 'prune'
      else
        _values 'volume' 'all' 'playwright'
      fi
      ;;
  esac
}

compdef _cb cb
