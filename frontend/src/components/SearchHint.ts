// Both boxes that search sessions say the same thing when you click into
// them. Searching by date is not discoverable from a placeholder reading
// "Find a session", so the hint appears on focus rather than sitting there
// permanently and adding noise to a resting screen. It stays in the
// accessibility tree either way, referenced by aria-describedby, so it is
// announced when the field takes focus.
export const SEARCH_HINT = "Search by date works too";
