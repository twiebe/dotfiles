# global installatio
if [ -x "/opt/homebrew/bin/brew" ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# user-local installation
if [ -x "~/.Homebrew/bin/brew" ]; then
  eval "$(~/.Homebrew/bin/brew shellenv)"
fi
