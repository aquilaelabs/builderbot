#!/bin/sh
# Which of this host's containers have an update waiting.
#
# Unraid's own version column cannot say any more: it asks each registry for
# the Docker manifest types and an image published as an OCI index answers 404,
# which it reports as "not available". Most of ghcr and every LinuxServer image
# is an index now, so most of a typical box reads as unknown. The pull still
# works; it is only the question that broke.
#
# This asks the question properly. For each container: the digest its image was
# pulled as, against the digest its registry serves for that tag now. Different
# means an update is waiting. It reads and compares, and changes nothing.
#
#   sh docker-updates.sh              every container on this host
#   sh docker-updates.sh IMAGE...     just those
#
# Authentication is whatever the registry asks for: the 401 names its own token
# endpoint in WWW-Authenticate and that is what gets used, so ghcr, lscr.io
# (which points at ghcr), Docker Hub and anything else work without a table of
# special cases here. A private image with no credential on this host says so
# rather than reading as up to date.
set -u
ACC='application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'

# The digest a registry serves for one tag right now, or "" and a reason on
# stderr. Anonymous: this asks what a public pull would get.
remote_digest () {
    api=$1 path=$2 tag=$3
    hdr=$(curl -sI --max-time 25 -H "Accept: $ACC" "$api/v2/$path/manifests/$tag" 2>/dev/null)
    code=$(printf '%s' "$hdr" | head -1 | awk '{print $2}')
    if [ "$code" = 401 ]; then
        auth=$(printf '%s' "$hdr" | tr -d '\r' | sed -n 's/^[Ww][Ww][Ww]-[Aa]uthenticate: Bearer //p')
        realm=$(printf '%s' "$auth" | sed -n 's/.*realm="\([^"]*\)".*/\1/p')
        service=$(printf '%s' "$auth" | sed -n 's/.*service="\([^"]*\)".*/\1/p')
        scope=$(printf '%s' "$auth" | sed -n 's/.*scope="\([^"]*\)".*/\1/p')
        [ -n "$realm" ] || { echo "no auth realm offered" >&2; return 1; }
        tok=$(curl -s --max-time 20 "$realm?service=$service&scope=${scope:-repository:$path:pull}" \
              | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
        [ -n "$tok" ] || { echo "private, and this host has no credential for it" >&2; return 1; }
        hdr=$(curl -sI --max-time 25 -H "Authorization: Bearer $tok" -H "Accept: $ACC" \
              "$api/v2/$path/manifests/$tag" 2>/dev/null)
        code=$(printf '%s' "$hdr" | head -1 | awk '{print $2}')
    fi
    if [ "$code" != 200 ]; then echo "the registry answered $code" >&2; return 1; fi
    printf '%s' "$hdr" | tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p'
}

command -v docker >/dev/null 2>&1 || { echo "no docker here" >&2; exit 1; }
if [ $# -eq 0 ]; then
    # shellcheck disable=SC2046  # one image per argument is the point
    set -- $(docker ps -a --format '{{.Image}}' | sort -u)
    [ $# -gt 0 ] || { echo "no containers here"; exit 1; }
fi

for img in "$@"; do
    ref=${img%%@*}
    repo=$ref; tag=latest
    last=${ref##*/}
    case "$last" in *:*) tag=${last##*:}; repo=${ref%:*} ;; esac
    first=${repo%%/*}
    case "$first" in
        *.*|*:*) reg=$first; path=${repo#*/} ;;
        *) reg=docker.io; case "$repo" in */*) path=$repo ;; *) path=library/$repo ;; esac ;;
    esac
    case "$reg" in
        docker.io) api=https://registry-1.docker.io ;;
        *)         api="https://$reg" ;;
    esac

    # What this host actually pulled. An image built here has no RepoDigest,
    # and there is nothing to compare it against.
    local_d=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$img" 2>/dev/null \
              | sed -n "s|^${repo}@||p" | head -1)
    if [ -z "$local_d" ]; then
        printf '%-46s %s\n' "$img" "not from a registry (built here?)"
        continue
    fi
    if ! remote_d=$(remote_digest "$api" "$path" "$tag" 2>/tmp/.du.$$); then
        printf '%-46s %s\n' "$img" "cannot tell: $(cat /tmp/.du.$$)"
        rm -f /tmp/.du.$$; continue
    fi
    rm -f /tmp/.du.$$
    if [ "$local_d" = "$remote_d" ]; then
        printf '%-46s %s\n' "$img" "up to date"
    else
        short=$(printf '%s' "${remote_d#*:}" | cut -c1-12)
        printf '%-46s %s\n' "$img" "UPDATE READY (registry is at $short)"
    fi
done
