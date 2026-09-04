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
    'up:start the box and run claude in it'
    'down:remove this box'
    'ls:list boxes'
    'exec:run a command inside the box'
    'shell:zsh inside the box'
    'recreate:replace the container, keeping the image'
    'rebuild-image:rebuild the shared image'
    'update-claude:rebuild with the newest claude-code, then recreate'
    'config:show or set this box'"'"'s settings'
  )
  features=(docker go playwright rust sqlx)

  if (( CURRENT == 2 )); then
    _describe -t commands 'cb command' subcommands
    _values 'option' '--docker' '--no-docker' '--force' '--dry-run' '--help'
    return
  fi

  case "${words[2]}" in
    down) _values 'scope' '--all' '--any' '-y' ;;
    ls) _values 'scope' '--any' ;;
    rebuild-image)
      _values 'option' '--no-cache' \
        ${^features/#/--with-} ${^features/#/--without-}
      ;;
    config) _values 'setting' 'docker' 'force' '--prune' ;;
  esac
}

compdef _cb cb
