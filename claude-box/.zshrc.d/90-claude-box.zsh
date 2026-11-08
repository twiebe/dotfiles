# cb itself and its completion come from the claude-box repo, which
# dotfiles-init-claude-box checks out and installs.

alias cbc='cb --continue'

# The voice of `say` in a box started with `cb --speak`. Without it cb falls
# back to spd-say (say on the Mac).
if (( $+commands[piper] && $+commands[pw-play] )) \
    && [[ -r ~/.local/share/piper/de_DE-thorsten-high.onnx ]]; then
  export CB_SPEAK_COMMAND="piper -m ${HOME}/.local/share/piper/de_DE-thorsten-high.onnx --output-raw 2>/dev/null | pw-play --raw --format s16 --rate 22050 --channels 1 -"
fi
