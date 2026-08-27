# base
export ZSH="$HOME/.oh-my-zsh"

# updates
zstyle ':omz:update' mode disabled

# theme
if [[ ! -v ZSH_THEME ]]; then
  ZSH_THEME="refined"
fi

# tmux
ZSH_TMUX_CONFIG="${HOME}/.config/tmux/tmux.conf"

# async prompt
#
# Forks a background job per prompt to precompute git_prompt_info. An empty
# ZSH_THEME means 40-starship.zsh found starship and took over the prompt, so
# no theme is left to consume the result and the fork is pure overhead. On a
# box without starship the fallback theme does render git_prompt_info, and
# there the async job is what keeps the prompt off the git status scan.
if [[ -z "$ZSH_THEME" ]]; then
  zstyle ':omz:alpha:lib:git' async-prompt no
fi

# plugins
plugins=(direnv fzf git sudo tmux)

source $ZSH/oh-my-zsh.sh

