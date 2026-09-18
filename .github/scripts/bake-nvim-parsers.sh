#!/usr/bin/env bash

# Builds every tree-sitter parser LazyVim asks for and packs it with its
# queries into OUTDIR/nvim-parsers-<platform>.tar.gz, plus OUTDIR/commit with
# the nvim-treesitter commit it was built from. nvim-parsers installs the
# result on other machines.
#
# Needs nvim, tree-sitter, a C compiler, curl, tar and git on PATH, and this
# repo's nvim config as ~/.config/nvim. Runs in CI and in a throwaway
# container alike.
#
#   bake-nvim-parsers.sh OUTDIR

set -euo pipefail

out=${1:?usage: bake-nvim-parsers.sh OUTDIR}
lock="${XDG_CONFIG_HOME:-$HOME/.config}/nvim/lazy-lock.json"
data="${XDG_DATA_HOME:-$HOME/.local/share}/nvim"
site="$data/site"
stamp="$site/.nvim-parsers"

commit=$(sed -nE 's/.*"nvim-treesitter": \{.*"commit": "([0-9a-f]+)".*/\1/p' "$lock")
if [[ -z "$commit" ]]; then
  echo "bake-nvim-parsers: no nvim-treesitter entry in $lock" >&2
  exit 1
fi

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) platform=linux-x86_64 ;;
  Linux-aarch64) platform=linux-aarch64 ;;
  Darwin-arm64) platform=darwin-arm64 ;;
  *)
    echo "bake-nvim-parsers: unsupported platform $(uname -s) $(uname -m)" >&2
    exit 1
    ;;
esac

# The cc crate behind `tree-sitter build` adds -Wall unless CFLAGS is set,
# and gcc with -Wall needs 5 GB for the gitcommit parser. The nvim config
# handles this for its own builds; the direct build below needs it here.
export CFLAGS="${CFLAGS:--O2}"

rm -rf "$site/parser" "$site/queries" "$stamp"
mkdir -p "$site" "$out"

# A stamp switches the config into "parsers are managed externally" mode, so
# the restore installs plugins without also starting to compile parsers.
echo "$commit" > "$stamp"
nvim --headless "+Lazy! restore" +qa

# The list LazyVim would install, computed from the config with the stamp
# gone again.
rm -f "$stamp"
langs=$(nvim --headless \
  +'lua io.stdout:write(table.concat(LazyVim.opts("nvim-treesitter").ensure_installed, " "))' \
  +qa 2>/dev/null)
echo "building: $langs"

# Plain nvim-treesitter without the config: one install call, waited for.
LANGS="$langs" nvim --headless -u NONE --cmd "set rtp^=$data/lazy/nvim-treesitter" \
  +'lua local ok = require("nvim-treesitter").install(vim.split(vim.env.LANGS, " "), { summary = true }):wait(30 * 60 * 1000); vim.cmd(ok and "qa!" or "cquit 1")'

missing=()
for lang in $langs; do
  [[ -f "$site/parser/$lang.so" ]] || missing+=("$lang")
done
if (( ${#missing[@]} > 0 )); then
  echo "bake-nvim-parsers: parsers missing after install: ${missing[*]}" >&2
  exit 1
fi

echo "$commit" > "$stamp"
tar -czf "$out/nvim-parsers-$platform.tar.gz" -C "$site" parser queries .nvim-parsers
echo "$commit" > "$out/commit"
echo "baked $(ls "$site/parser" | wc -l | tr -d ' ') parsers for $platform ($commit)"
