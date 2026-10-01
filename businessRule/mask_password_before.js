/*
 * BARQ G4 - Mask passwords before the incident is saved (regex).
 *
 * Business Rule settings:
 *   Application: Sprints X Barq
 *   Table:  Incident [incident]
 *   When:   before    Insert: true    Update: true    Order: 50
 *   Filter: Short description changes  OR  Description changes
 *
 * Replaces the value after a password keyword with ***, e.g.
 *   "password: Summer2024!"   -> "password: ***"
 *   "my pwd is abc123"        -> "my pwd is ***"
 *   'passcode = "my secret"'  -> "passcode = ***"
 * A separator (":", "=", "is", "was") is required after the keyword, so
 * "password reset" or "password expired" are left alone.
 */
(function executeRule(current, previous /*null when async*/) {
    var PASSWORD_PATTERN = new RegExp(
        "\\b(password|passwd|pwd|passcode|passphrase|pin)" +   // keyword
        "(\\s*(?:(?:is|was)\\s*[:=]?|[:=])\\s*)" +             // separator
        "(\"[^\"]*\"|'[^']*'|[^\\s,;]+)",                     // value
        "gi"
    );
    var FIELDS = ["short_description", "description"];

    for (var i = 0; i < FIELDS.length; i++) {
        var value = current.getValue(FIELDS[i]);
        if (!value) {
            continue;
        }
        var masked = value.replace(PASSWORD_PATTERN, "$1$2***");
        if (masked != value) {
            current.setValue(FIELDS[i], masked);
            gs.info("BARQ G4 Password mask: masked " + FIELDS[i] + " on " + current.getValue("number"));
        }
    }
})(current, previous);
