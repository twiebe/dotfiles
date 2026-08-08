# base
export ZSH="$HOME/.oh-my-zsh"

# updates
zstyle ':omz:update' mode disabled

# theme
if [[ ! -v ZSH_THEME ]]; then
  ZSH_THEME="refined"
fi

# tmux
ZSH_TMUX_CONFIG="${XDG_CONFIG_HOME}/tmux/tmux.conf"

# plugins
plugins=(direnv git sudo tmux)

source $ZSH/oh-my-zsh.sh

