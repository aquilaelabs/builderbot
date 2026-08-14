# BuilderBot default shell profile.
# Copied into /home/builder on first start; edit freely, it is never overwritten.

case $- in *i*) ;; *) return ;; esac

HISTCONTROL=ignoreboth
HISTSIZE=10000
HISTFILESIZE=50000
shopt -s histappend checkwinsize

export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
export EDITOR="${EDITOR:-nano}"
export WORKSPACE="${WORKSPACE:-/workspace}"

# Colour prompt: user@builderbot:cwd$
PS1='\[\033[01;32m\]\u@builderbot\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '

alias ll='ls -alFh --color=auto'
alias la='ls -A --color=auto'
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias ws='cd "$WORKSPACE"'
alias gs='git status'
alias gl='git log --oneline --graph --decorate -20'

# mise manages per-project tool versions when a project has a .mise.toml
command -v mise >/dev/null 2>&1 && eval "$(mise activate bash)"

[ -f "$HOME/.bash_aliases" ] && . "$HOME/.bash_aliases"

if [ -z "${BUILDERBOT_MOTD_SHOWN:-}" ]; then
    export BUILDERBOT_MOTD_SHOWN=1
    echo "BuilderBot — 'bb status' for an overview, 'claude' to start a session."
fi
