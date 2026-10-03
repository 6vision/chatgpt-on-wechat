# encoding:utf-8
"""A scroll's distance is not its timeout.

``browser`` multiplexes a dozen actions behind one ``action`` argument, so the
model reaches for a shared set of parameters -- and the tool's schema documents
``timeout`` as "Timeout in milliseconds", the meaning it carries for navigate,
click, fill, select and wait alike.

``_do_scroll`` did not read the distance from anywhere the schema advertises. It
took it from ``timeout``:

    amount = args.get("timeout", 500)  # reuse timeout field or default

The distance is pixels -- ``BrowserService.scroll`` hands it straight to
``page.mouse.wheel`` as a delta -- so the two fields were being read as the same
number. A model that asked for a ten second wait on a scroll scrolled 10000
pixels, which on a long page is most of the document in a single call, and the
tool reported success. There was no way to ask for both: the schema never
listed a distance field at all, so a model that guessed the right name found
``amount`` honoured only when it happened to pass it *instead of* a timeout.

These pin the two halves of the fix: ``timeout`` stays a timeout and does not
move the page further than the documented default, and the distance is
reachable through a field the schema actually advertises.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# The default ``BrowserService.scroll`` applies, and the one ``_do_scroll``
# documents by not passing anything: a half-screen nudge.
DEFAULT_DISTANCE = 500


class _RecordingService:
    """Stands in for the browser, keeping what it was asked to scroll."""

    def __init__(self):
        self.calls = []

    def scroll(self, direction="down", amount=DEFAULT_DISTANCE):
        self.calls.append({"direction": direction, "amount": amount})
        return {"scrolled": direction, "scrollY": 0, "scrollHeight": 9000}


class ScrollDistanceIsNotTheTimeoutField(unittest.TestCase):

    def setUp(self):
        from agent.tools.browser.browser_tool import BrowserTool

        self.tool = BrowserTool({})
        self.service = _RecordingService()
        # Set directly so no browser is launched and no engine probe runs.
        self.tool._service = self.service

    def test_a_timeout_on_a_scroll_does_not_become_the_distance(self):
        """The model asked to wait ten seconds. It gets the documented default
        distance, not a ten-thousand-pixel jump down the page."""
        result = self.tool._do_scroll({"direction": "down", "timeout": 10000})

        self.assertEqual(result.status, "success")
        self.assertEqual(len(self.service.calls), 1)
        self.assertEqual(
            self.service.calls[0]["amount"], DEFAULT_DISTANCE,
            "a timeout in milliseconds was scrolled as pixels",
        )

    def test_the_distance_comes_from_the_amount_field(self):
        self.tool._do_scroll({"direction": "down", "amount": 250})

        self.assertEqual(self.service.calls[0]["amount"], 250)

    def test_both_fields_together_are_each_read_as_themselves(self):
        """Naming a distance and a wait is the call the old code could not
        express: the distance has to survive the timeout being present."""
        self.tool._do_scroll({"direction": "down", "amount": 250, "timeout": 10000})

        self.assertEqual(self.service.calls[0]["amount"], 250)

    def test_the_schema_advertises_the_distance_field(self):
        """A field the schema omits is a field the model cannot name, which is
        how the distance ended up being read out of ``timeout`` in the first
        place."""
        from agent.tools.browser.browser_tool import BrowserTool

        properties = BrowserTool.params["properties"]
        self.assertIn("amount", properties)
        # Pixels, stated as pixels: the mistake this file is about is a number
        # read as the wrong unit.
        self.assertIn("pixel", properties["amount"]["description"].lower())


if __name__ == "__main__":
    unittest.main()
