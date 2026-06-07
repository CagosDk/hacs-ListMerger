"""Constants for List Merger."""

DOMAIN = "list_merger"
PLATFORMS = ["todo"]

# Config keys
CONF_MASTER_NAME = "master_name"
CONF_MASTER_TYPE = "master_type"
CONF_MASTER_ENTITY_ID = "master_entity_id"
CONF_SOURCES = "sources"
CONF_SOURCE_ENTITY_ID = "source_entity_id"
CONF_DIRECTION = "direction"
CONF_DELETE_ON_MERGE = "delete_on_merge"
CONF_DUPLICATE_HANDLING = "duplicate_handling"
CONF_COMPLETED_BEHAVIOR = "completed_behavior"

# Master type values
MASTER_TYPE_NEW = "new"
MASTER_TYPE_EXISTING = "existing"

# Direction values
DIRECTION_ONE_WAY = "one_way"
DIRECTION_TWO_WAY = "two_way"

# Duplicate handling values
DUPLICATE_DEDUPLICATE = "deduplicate"
DUPLICATE_KEEP_ALL = "keep_all"

# Completed behavior values
COMPLETED_SYNC_BACK = "sync_back"
COMPLETED_MASTER_ONLY = "master_only"
COMPLETED_DELETE_BOTH = "delete_both"

# Storage
STORAGE_VERSION = 1
