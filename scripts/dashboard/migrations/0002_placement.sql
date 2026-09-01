-- 0002: what phase 4 (jobs and the queue) needs that 0001 did not carry.
--
-- Nodes gain os and arch as columns of their own (docs/nodes.md §15 door 9):
-- placement selects on them, so they are fields and not a string inside the
-- reported census. Jobs gain the three things a job the operator can watch
-- and stop needs: the step it is on, the reason it ended badly, and a cancel
-- flag the runner reads — a request to stop is a fact about the job, kept
-- with it, not a signal that was sent once.
--
-- Same rules as 0001: TEXT/INTEGER only, one statement per paragraph. ADD
-- COLUMN with a constant default is the one ALTER both engines spell the
-- same way, which is why these are four small statements and not a rebuild.

ALTER TABLE nodes ADD COLUMN os TEXT NOT NULL DEFAULT '';

ALTER TABLE nodes ADD COLUMN arch TEXT NOT NULL DEFAULT '';

ALTER TABLE jobs ADD COLUMN step TEXT NOT NULL DEFAULT '';

ALTER TABLE jobs ADD COLUMN error TEXT NOT NULL DEFAULT '';

ALTER TABLE jobs ADD COLUMN cancel INTEGER NOT NULL DEFAULT 0;
