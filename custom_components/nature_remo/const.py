"""Constants for the Nature Remo integration."""

from datetime import timedelta

DOMAIN = "nature_remo"
UPDATE_INTERVAL = timedelta(seconds=60)

# How many consecutive real polls must miss an id before its registry entry
# (entity or device) is deleted. Removal is destructive — it takes the user's
# customizations (name, area, icon, automations referencing the entity) with
# it — so a single truncated API response must never trigger it. Three polls
# in a row without the id means it is genuinely gone from the account.
STALE_POLLS_BEFORE_REMOVAL = 3
