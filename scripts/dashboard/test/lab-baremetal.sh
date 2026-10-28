#!/usr/bin/env bash
# The shell lab-baremetal.mjs runs as root in its VM (R90 step 9), kept here
# rather than in the suite's own text: what a session on the controller's own
# node must never reach, tried, and the same tries from inside a session's
# view. The suite sends this file and a line naming the function to run.

# tries: each thing a session may not reach, one line each, "refused" or
# "REACHED", as whichever account runs it.
tries() {
    local st
    st="$(sed -n 's/^DASHBOARD_STATE=//p' /etc/builderbot-controller/controller.env 2>/dev/null)"
    [ -n "$st" ] || st=/var/lib/builderbot-controller/config
    try() { if "$@" >/dev/null 2>&1; then echo "REACHED $*"; else echo "refused $*"; fi; }
    try cat "$st/users.json"
    try ls "$st"
    try cat /etc/builderbot-controller/controller.env
    try ls /etc/builderbot-controller/secrets
    try cat /run/builderbot/secrets.env
    try ls /run/builderbot
    # ssh-add exits 2 when it cannot reach an agent, 1 for an empty one.
    try sh -c 'SSH_AUTH_SOCK=/run/builderbot-controller/ssh-agent.sock ssh-add -l; [ $? -ne 2 ]'
    try curl -s -m 5 --unix-socket /run/docker.sock http://localhost/version
}

# covers: inside a view, every folder the wall names is there empty or not at all.
covers() {
    local p
    for p in $(sed -n 's/^COVER=//p' /etc/bb-session.wall | tr ':' ' '); do
        if [ -e "$p" ] && [ -n "$(ls -A "$p" 2>/dev/null)" ]; then echo "REACHED $p (not empty)"; else echo "refused $p"; fi
    done
}

# outside WHO: the tries as an account of the node's, outside any view.
outside() {
    { declare -f tries; echo tries; } > /tmp/tries.sh
    chmod 755 /tmp/tries.sh
    sudo -u "$1" bash /tmp/tries.sh
}

# start_install REF: the repository's REF unpacked and installed, in the
# background; /root/install.rc says how it ended.
start_install() {
    set -e
    mkdir -p /root/bb && cd /root/bb
    curl -fsSL "https://github.com/aquilaelabs/builderbot/archive/$1.tar.gz" | tar -xz --strip-components=1
    bash nodes/install-controller.sh --check > /root/check.log 2>&1; echo $? > /root/check.rc
    setsid bash -c 'bash nodes/install-controller.sh --install > /root/install.log 2>&1; echo $? > /root/install.rc' \
        < /dev/null > /dev/null 2>&1 &
    echo started
}

# status: the dashboard's answer on its port, the service, the release, the
# account and the nodes as bb lists them.
status() {
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/; echo
    systemctl is-active builderbot-controller
    readlink /opt/builderbot
    id builderbot
    bb nodes 2>&1 | tail -3
}

# inside: the tries and the covers inside a session's view, built by
# bb-session as a session's is, for a project made for it.
inside() {
    local acct=u_0000a9a9 d
    mkdir -p /workspace/labp && chown builder: /workspace/labp
    d="/home/builder/.cache/builderbot/u/$acct/project/labp"
    sudo -u builder mkdir -p "$d"
    sudo -u builder sh -c "printf 'PATH=/usr/local/bin:/usr/bin:/bin\0' > $d/env"
    # In the project's tree, which the view keeps: its /tmp is its own.
    { declare -f tries covers; echo tries; echo covers; } > /workspace/labp/.inview.sh
    chmod 755 /workspace/labp/.inview.sh
    cd /tmp && sudo -u builder sudo -n /usr/local/sbin/bb-session enter --project labp --account "$acct" \
        --home /home/builder --cwd /workspace/labp --env "$d/env" -- /bin/bash /workspace/labp/.inview.sh 2>&1 \
        || echo "enter-rc=$?"
}

# start_update REF: the repository's REF unpacked beside the install and the
# installed release's --update run from it (R90 step 5), in the background;
# /root/update.rc says how it ended.
start_update() {
    set -e
    rm -rf /root/bb-next && mkdir -p /root/bb-next && cd /root/bb-next
    curl -fsSL "https://github.com/aquilaelabs/builderbot/archive/$1.tar.gz" | tar -xz --strip-components=1
    setsid bash -c 'bash /opt/builderbot/nodes/install-controller.sh --update --from /root/bb-next > /root/update.log 2>&1; echo $? > /root/update.rc' \
        < /dev/null > /dev/null 2>&1 &
    echo started
}

# rollback: the installed release's --rollback, waited for; its exit code.
rollback() {
    bash /opt/builderbot/nodes/install-controller.sh --rollback > /root/rollback.log 2>&1; echo "rc=$?"
    tail -5 /root/rollback.log
}

# release: the release the install runs now (its link and its stamp).
release() {
    readlink /opt/builderbot
    sed -n 's/^BB_VERSION=//p' /opt/builderbot/build.env
    sed -n 's/^STATE_VERSION=//p' "$(sed -n 's/^DASHBOARD_STATE=//p' /etc/builderbot-controller/controller.env)/state.json" 2>/dev/null \
        || python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' \
            "$(sed -n 's/^DASHBOARD_STATE=//p' /etc/builderbot-controller/controller.env)/state.json" 2>/dev/null || true
}
