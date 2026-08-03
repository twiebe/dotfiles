#!/bin/sh
# Print a full-width, timestamped divider. Used by the tmux "mark" binding,
# which redirects this into the pane's tty so the line shows up in the output
# stream even while something like `kubectl logs -f` is still writing.
#
# $1: target width in columns (tmux passes #{pane_width})
#
# length() is only ever called on the ASCII timestamp: awk counts bytes, and a
# box-drawing character is three of them, so measuring the divider itself would
# come out short.
w="${1:-80}"
awk -v w="$w" -v t="$(date +%H:%M:%S)" \
    'BEGIN { n = w - length(t) - 4; s = "── " t " "; while (i++ < n) s = s "─"; print s }'
