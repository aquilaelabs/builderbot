-- 0003: every node does everything (the operator's decision, 2 Sep).
--
-- Capabilities stopped being a setting. A node is not "for" docker or for
-- building any more: a project names ONE node and that node does all of its
-- work, and what the project can actually DO there is what is installed on
-- it, which the census already reports as toolchains. So the operator is no
-- longer asked, and every node carries the full set.
--
-- The column stays, and so does the node-side refusal it feeds (docs/nodes.md
-- §15 door 7: an agent refuses a job outside what it enrolled with, and
-- retrofitting that onto a deployed fleet means re-enrolling all of it). What
-- went is the choosing, not the mechanism: a restricted node is still
-- expressible, it is just not something anybody has to configure to get work
-- done.
--
-- local is left alone on purpose: it is the controller, not a node a project
-- is assigned to, and docker-host on it would mean containers beside /config
-- and the dashboard credential (docs/nodes.md §12).

UPDATE nodes SET capabilities = '["docker-host", "package-build", "deploy-target"]'
WHERE kind != 'local' AND state != 'retired';
