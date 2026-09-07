"""Send changes, confirm persistent problems, and occasionally check in quietly."""
from copy import deepcopy


class ReportingPolicy:
    def __init__(self, checkin_seconds=3600, confirm_seconds=120):
        self.checkin_seconds = checkin_seconds
        self.confirm_seconds = confirm_seconds
        self.last = None
        self.last_sent = 0
        self.pending_confirmation = None

    def select(self, payload, now):
        flags = sorted(x for x in payload["conditions"] if x != "comfortable")
        previous_flags = sorted(x for x in self.last["conditions"] if x != "comfortable") if self.last else []
        condition_change = flags != previous_flags
        deltas = {"soil_moisture":5, "temperature_f":3, "humidity":5, "battery_percent":5}
        changed = self.last is None or any(abs(payload["readings"][key] - self.last["readings"][key]) >= delta for key,delta in deltas.items())
        confirmation_due = self.pending_confirmation is not None and now >= self.pending_confirmation
        if condition_change:
            self.pending_confirmation = now + self.confirm_seconds if flags else None
        if self.last is None and flags:
            self.pending_confirmation = now + self.confirm_seconds
        if self.last is None or condition_change or changed or confirmation_due:
            kind = "event"
        elif now - self.last_sent >= self.checkin_seconds:
            kind = "checkin"
        else:
            return None
        if confirmation_due and not condition_change:
            self.pending_confirmation = None
        result = deepcopy(payload)
        result["schema_version"] = "1.1"
        result["report_kind"] = kind
        # Caller commits policy only after successful delivery (or restores state on failure).
        self.last = deepcopy(payload)
        self.last_sent = now
        return result
