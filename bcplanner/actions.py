"""The action vocabulary shared by the search, the replay checker and the report.

An action is a small tuple:
  ("single", event_id)   one rare-ticket roll on that banner
  ("eleven", event_id)   an 11-draw (or 15-roll step-up) on that banner, paid with cat food
  ("plat",)              one platinum ticket on the platinum banner
  ("legend",)            one legend ticket on the legend banner
  ("clock", "tomorrow")  set the device date forward one day
  ("clock", "today")     set the device date back to the plan date
"""

from __future__ import annotations

SINGLE = "single"
ELEVEN = "eleven"
PLAT = "plat"
LEGEND = "legend"
CLOCK = "clock"

TODAY = 0
TOMORROW = 1

CF_UNIT = 750            # cat food is counted in 750 CF units: a normal 11-draw is 2, a discounted first draw is 1
CF_ELEVEN = 1500
CF_ELEVEN_DISCOUNT = 750


def describe(action: tuple, banner_names: dict[str, str] | None = None) -> str:
    kind = action[0]
    if kind == SINGLE:
        return f"Single (rare ticket) on {_bn(action[1], banner_names)}"
    if kind == ELEVEN:
        return f"11-draw on {_bn(action[1], banner_names)}"
    if kind == PLAT:
        return "Platinum ticket"
    if kind == LEGEND:
        return "Legend ticket"
    if kind == CLOCK:
        return "Set device date forward one day" if action[1] == "tomorrow" else "Set device date back to today"
    return str(action)


def _bn(event_id: str, names: dict[str, str] | None) -> str:
    if names and event_id in names:
        return names[event_id]
    return event_id
