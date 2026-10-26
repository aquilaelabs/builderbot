-- 0007: each session and each project's containers kept to their own
-- network on every node (the operator, 26 Oct): a node that had either
-- switched off has it on again, since which projects reach each other is
-- their Reads and not a node's choice. The switches are deprecated in 0.8.0
-- and go in 0.9.0. A hosting-only node runs no sessions, so its sessions'
-- switch is left as it was.

UPDATE nodes SET config = json_set(config, '$.session_net', json('true'))
 WHERE kind = 'agent' AND json_extract(config, '$.session_net') = 0
   AND COALESCE(json_extract(config, '$.host_only'), 0) = 0;

UPDATE nodes SET config = json_set(config, '$.container_net', json('true'))
 WHERE kind = 'agent' AND json_extract(config, '$.container_net') = 0;
