#!/bin/sh
# Build the container image on THIS machine, from THIS checkout, and tag it
# where the running container already looks. No registry is involved, which
# is the point: it is the way to update when the pull is refused.
#
# Run it on the machine whose docker serves the container. On the Unraid host
# the projects share carries this repo, so that is:
#
#   sh /mnt/user/development/projects/BuilderBot/tools/build-image-here.sh
#
# then Docker tab, the container, Edit, Apply. Apply recreates it on whatever
# image is local, which is now this one. Nothing else changes: the template,
# the paths and the appdata are untouched.
#
# The three stamps are computed the way .github/workflows/build-image.yml
# computes them, so `bb status`, the dashboard header and `bb catchup` say the
# same thing about a local build as about a CI one. A tree with uncommitted
# changes says so in the version, because a build nobody can identify is
# worse than no build.
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
IMAGE=${BB_IMAGE:-ghcr.io/stencil-projects/builderbot}

command -v docker >/dev/null 2>&1 || {
    echo "no docker here. Run this on the machine whose daemon serves the container." >&2
    exit 1
}
[ -f Dockerfile ] || { echo "no Dockerfile beside this script's repo root" >&2; exit 1; }

rev=$(git rev-parse HEAD)
short=$(git rev-parse --short=7 HEAD)
built=$(date -u +%Y-%m-%dT%H:%MZ)
branch=$(git rev-parse --abbrev-ref HEAD)
target=$(head -1 VERSION 2>/dev/null | tr -d '[:space:]')
ordinal=$(git rev-list --count HEAD)
# status, not diff: an untracked file is a change this build will contain
# and `git diff HEAD` does not see one.
dirty=''
[ -z "$(git status --porcelain 2>/dev/null)" ] || dirty='.dirty'

if ! printf '%s' "$target" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    v="$short"
elif tag=$(git describe --tags --exact-match HEAD 2>/dev/null); then
    v="${tag#v}"
else
    v="${target}-dev.${ordinal}+${short}"
fi
v="${v}${dirty}"

# Said before it starts, because the commonest way to get this wrong is to
# build a checkout that is not the one you meant: a branch a session left
# behind, or a tree that has not been pulled.
echo "building $IMAGE:latest"
echo "  from    $branch at $short${dirty:+ (uncommitted changes included)}"
echo "  version $v"
echo "  built   $built"
echo
echo "Ctrl-C in the next five seconds if that is not the tree you meant."
sleep 5

docker build -t "$IMAGE:latest" \
    --build-arg IMAGE_REV="$rev" \
    --build-arg IMAGE_BUILT="$built" \
    --build-arg IMAGE_VERSION="$v" \
    .

echo
echo "built and tagged $IMAGE:latest as $v"
echo "Now recreate the container so it runs this image: Docker tab, the"
echo "container, Edit, Apply. A restart is NOT enough; a container is bound"
echo "to the image it was created from."
