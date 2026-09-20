-- 0004: what BuilderBot installs from its catalogue is a toolchain (the
-- operator's word, 19 Sep), in the store, the job and the census alike.
--
-- A job of that kind is typed toolchain; a node's desired stores and the
-- stores its census reported name the toolchain store under that role; and
-- the census's per-recipe versions are toolchain_versions. The next hello of
-- a current agent reports the new names anyway; the desired config is the
-- operator's and would not come back by itself.

UPDATE jobs SET type = 'toolchain' WHERE type = 'package';

UPDATE nodes SET config = json_remove(
    json_set(config, '$.desired.stores.toolchains', json_extract(config, '$.desired.stores.packages')),
    '$.desired.stores.packages')
  WHERE json_valid(config) AND json_extract(config, '$.desired.stores.packages') IS NOT NULL;

UPDATE nodes SET reported = json_remove(
    json_set(reported, '$.stores.toolchains', json(json_extract(reported, '$.stores.packages'))),
    '$.stores.packages')
  WHERE json_valid(reported) AND json_extract(reported, '$.stores.packages') IS NOT NULL;

UPDATE nodes SET reported = json_remove(
    json_set(reported, '$.toolchain_versions', json(json_extract(reported, '$.packages_versions'))),
    '$.packages_versions')
  WHERE json_valid(reported) AND json_extract(reported, '$.packages_versions') IS NOT NULL;
