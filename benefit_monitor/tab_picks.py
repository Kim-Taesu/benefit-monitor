"""The weekly tab picks (festival and benefit 2026-11-14, 청약 2026-11-18) in one place.

Every publish path (publish, public_snapshot, auto_release), the AI run upload (cloud_daily) and the restore
(mirror) walk this list, so a new pick kind is one row here, not five hand edits. Module names are strings so
this file imports nothing."""
from collections import namedtuple

TabPick = namedtuple('TabPick', 'name key local remote module basis')

TAB_PICKS = (
    TabPick('festival', 'festival_pick', 'cache/festival_pick/pick.json', 'ai-festival-pick.json', 'festival_pick', 'festivals'),
    TabPick('benefit', 'benefit_pick', 'cache/benefit_pick/pick.json', 'ai-benefit-pick.json', 'benefit_pick', 'items'),
    TabPick('subscription', 'subscription_pick', 'cache/subscription_pick/pick.json', 'ai-subscription-pick.json',
            'subscription_pick', 'subscriptions'),
)
KEYS = tuple(p.key for p in TAB_PICKS)
