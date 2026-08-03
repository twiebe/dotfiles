export PATH="${HOME}/bin:${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

## oh-my-zsh
export ZSH="$HOME/.oh-my-zsh"
plugins=(git sudo tmux)
zstyle ':omz:update' mode disabled

# starship
if which starship 2>&1 > /dev/null; then
  eval "$(starship init zsh)"
  ZSH_THEME=""
else
  ZSH_THEME="refined"
fi

source $ZSH/oh-my-zsh.sh

# opts
unsetopt share_history

# includes
if [ -d ~/.zshrc.d ]; then
  setopt NULL_GLOB
  for fn in ~/.zshrc.d/*; do
    source "${fn}"
  done
  unsetopt NULL_GLOB
fi

test -f ~/.zshrc.local && source ~/.zshrc.local

if [ -d ~/.zshrc.local.d ]; then
  setopt NULL_GLOB
  for fn in ~/.zshrc.local.d/*; do
    source "${fn}"
  done
  unsetopt NULL_GLOB
fi
