DC_DEFAULT="$HOME/.confg/claude-box/devcontainer.json"

_dc_config_arg() {
  [ -f .devcontainer/devcontainer.json ] && echo "" || echo "--config $DC_DEFAULT"
}

dcup() {
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_dc_config_arg)
}

dcexec() {
  eval devcontainer exec --workspace-folder "\"$PWD\"" $(_dc_config_arg) -- "$@"
}

dcrecreate() {
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_dc_config_arg) --remove-existing-container
}

dcrebuild() {
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_dc_config_arg) --remove-existing-container --build-no-cache
}

claude-box() {
  dcup >/dev/null && dcexec claude "$@"
}

alias cb='claude-box'
alias cbc='claude-box --continue'
