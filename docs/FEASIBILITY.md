# Feasibility spike

Status after Phase 1. Live items require operator credentials and installations.

1. **Battle.net OAuth:** Implemented with browser authorization code flow, PKCE, state validation, and loopback-only callback. Live validation pending.
2. **Account character list:** Implemented against the protected WoW profile summary endpoint. Live validation pending.
3. **Profile/achievement/pet data:** Profile, achievements, account pets/mounts, equipment, professions, reputations, statistics, and completed quests are independently captured. Live validation pending.
4. **Raw JSON and SQLite:** Covered by automated tests.
5. **wow.export character representation:** Deferred to Phase 2; source profile/equipment are retained.
6. **Programmatic wow.export:** The adapter probes a versioned localhost `wow-timecapsule-bridge/v1` endpoint and executable version. No GUI automation is used.
7. **Character GLB export:** Deferred to Phase 2.
8. **Three.js GLB loading:** Deferred to Phase 4. The verifier validates GLB v2 containers when present.

Failure of item 6 does not block API archival. A bridge must bind only to `127.0.0.1` and remain behind the adapter.
