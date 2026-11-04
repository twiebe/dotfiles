# User-installed completions, e.g. claude-box's _cb. Before 50-omz.zsh, which
# runs compinit over whatever fpath holds by then.
fpath=("${XDG_DATA_HOME:-${HOME}/.local/share}/zsh/site-functions" $fpath)
