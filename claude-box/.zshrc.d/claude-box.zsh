CB_DEFAULT="$HOME/.config/claude-box/devcontainer.json"

_cb_config_arg() {
  [ -f .devcontainer/devcontainer.json ] && echo "" || echo "--config $CB_DEFAULT"
}

cbup() {
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_cb_config_arg)
}

cbexec() {
  eval devcontainer exec --workspace-folder "\"$PWD\"" $(_cb_config_arg) -- "$@"
}

cbrecreate() {
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_cb_config_arg) --remove-existing-container
}

cbrebuild() {
  eval devcontainer up --workspace-folder "\"$PWD\"" $(_cb_config_arg) --remove-existing-container --build-no-cache
}

claude-box() {
  cbup >/dev/null && cbexec claude "$@"
}

alias cb='claude-box'
alias cbc='claude-box --continue'
