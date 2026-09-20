"""Names shared by the investment modules (kept apart so they can import each other's parts without a cycle)."""

BROKERS = ("N26", "Commerzbank", "Sparkasse")  # banks that can hold investment bookings
ALWAYS_LISTED = ("N26", "Commerzbank")  # tabs that exist even before their first booking

UNKNOWN = "Unknown"  # nothing says what it bought (no plan covers that day, nothing typed in)
MANUAL = "Manual buys"  # bought outside every plan, while the household had plans running
