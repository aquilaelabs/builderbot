# The network probe (R178's proof): a container that tries what a project's
# container on a node must and must not reach, and says which. Built from
# this folder and shipped to a hosting-only node with
#   bb devapp new nettest --compose test/nettest/compose.yml --node NODE --env FILE
# then read with bb devapp log nettest (or docker logs on the node).
FROM alpine:3.20
RUN apk add --no-cache curl bind-tools iproute2 busybox-extras
COPY probe.sh /probe.sh
CMD ["/bin/sh", "/probe.sh"]
