# rcs
#
# ~/.zshrc.d and ~/.zshrc.local.d are merged into a single list that is sorted
# by file name across both directories, so a local file can be placed anywhere
# in the global order (e.g. ~/.zshrc.local.d/35-foo.zsh runs between the global
# 30-* and 40-* files). On identical file names the local one is sourced last
# and therefore wins.
typeset -a rcs
typeset rc sep=$'\x1f'

for rc in ~/.zshrc.d/*(-.N); do
  rcs+=("${rc:t}${sep}0${sep}${rc}")
done
for rc in ~/.zshrc.local.d/*(-.N); do
  rcs+=("${rc:t}${sep}1${sep}${rc}")
done

for rc in ${(o)rcs}; do
  source "${rc##*${sep}}"
done

unset rcs rc sep

test -f ~/.zshrc.local && source ~/.zshrc.local
