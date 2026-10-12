# encoding:utf-8
"""A run that answers on its last allowed turn keeps that answer.

``run_stream`` counts a turn before it calls the model, so a run that finishes
with a plain reply on its final allowed turn leaves ``turn == max_turns`` --
the same value a genuinely exhausted run reaches. The step-limit branch used to
test that value alone, so such a run paid for a second LLM call, had its answer
replaced by a step-limit summary, and left two consecutive ``assistant``
messages in the history callers persist.

For a scheduled task the overwrite is worse than cosmetic: silence is a valid
outcome there, and the summary replaces it with an apology addressed to a user
who never asked anything.
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.protocol.agent_stream import AgentStreamExecutor

ANSWER = "THE REAL ANSWER"
SUMMARY = "THE STEP LIMIT SUMMARY"
SILENCE = ""


class _CountingExecutor(AgentStreamExecutor):
    """The real agent loop, driven by a model that counts its calls.

    Each scripted response is ``(text, tool_names)``. The model appends its own
    assistant message the way the real one does, so the assertions see the
    history callers persist. The script runs out if the loop asks for one reply
    too many, which turns a spurious extra call into a loud failure instead of
    a silent IndexError somewhere later.
    """

    def __init__(self, script, max_turns, allow_empty_response=False):
        agent = SimpleNamespace(name="test-agent", messages=[], tools=[])
        super().__init__(
            agent=agent,
            model=SimpleNamespace(model="test-model"),
            system_prompt="",
            tools=[],
            max_turns=max_turns,
            messages=agent.messages,
            allow_empty_response=allow_empty_response,
        )
        self.script = list(script)
        self.calls = 0

    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        # Trimming needs a real Agent for token accounting and has no bearing
        # on the step-limit decision.
        return None

    def _validate_and_fix_messages(self):
        return None

    def _call_llm_stream(self, retry_on_empty=True):
        self.calls += 1
        text, names = self.script.pop(0)
        calls = [{"id": f"call-{n}", "name": n, "arguments": {}} for n in names]
        content = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool_use", "id": c["id"], "name": c["name"], "input": {}} for c in calls
        ]
        self.messages.append({"role": "assistant", "content": content})
        return text, calls, "end_turn"

    def _execute_tool(self, tool_call):
        return {"status": "success", "result": "ok", "execution_time": 0.01}


class MaxTurnsStepLimitTest(unittest.TestCase):
    def test_an_answer_on_the_only_allowed_turn_costs_one_model_call(self):
        executor = _CountingExecutor(
            script=[
                (ANSWER, []),
                (SUMMARY, []),  # only reachable if a second call is made
            ],
            max_turns=1,
        )

        response = executor.run_stream("do the thing")

        self.assertEqual(response, ANSWER)
        self.assertEqual(executor.calls, 1)

    def test_an_answer_after_tool_turns_costs_no_extra_model_call(self):
        # Two tool turns, then the answer on turn 3 of 3: one call per turn is
        # the whole budget, and the step-limit summary was a fourth.
        executor = _CountingExecutor(
            script=[
                ("", ["one"]),
                ("", ["two"]),
                (ANSWER, []),
                (SUMMARY, []),  # only reachable if a second call is made
            ],
            max_turns=3,
        )

        response = executor.run_stream("do the thing")

        self.assertEqual(response, ANSWER)
        self.assertEqual(executor.calls, 3)

    def test_a_normal_finish_leaves_no_duplicate_assistant_message(self):
        executor = _CountingExecutor(
            script=[("", ["one"]), (ANSWER, []), (SUMMARY, [])],
            max_turns=2,
        )

        executor.run_stream("do the thing")

        roles = [message["role"] for message in executor.agent.messages]
        self.assertEqual(
            [pair for pair in zip(roles, roles[1:]) if pair[0] == pair[1] == "assistant"],
            [],
        )
        # The reply that got persisted is the answer, not the summary.
        self.assertEqual(executor.agent.messages[-1]["content"], [{"type": "text", "text": ANSWER}])

    def test_a_run_that_really_exhausts_the_limit_still_summarises(self):
        # Turn 1 of 1 calls a tool, so the loop runs out of turns mid-work and
        # the step-limit summary is the intended outcome here.
        executor = _CountingExecutor(
            script=[("working", ["one"]), (SUMMARY, [])],
            max_turns=1,
        )

        response = executor.run_stream("do the thing")

        self.assertEqual(response, SUMMARY)
        self.assertEqual(executor.calls, 2)

    def test_the_step_limit_prompt_does_not_stay_in_the_history(self):
        """The genuine-exhaustion path is already clean; keep it that way.

        The summary prompt is injected as a user message and popped again, so
        what is left is the query, the tool turn and the summary. A leftover
        prompt would show up as a third user message here.
        """
        executor = _CountingExecutor(
            script=[("working", ["one"]), (SUMMARY, [])],
            max_turns=1,
        )

        executor.run_stream("do the thing")

        self.assertEqual(
            [message["role"] for message in executor.agent.messages],
            ["user", "assistant", "user", "assistant"],
        )

    def test_a_silent_scheduled_run_is_not_turned_into_an_apology(self):
        """Silence is a valid result for a scheduled task, so it must survive.

        The model answers nothing on its first and only turn: silence is the
        answer, and the step-limit branch used to overwrite it with the
        "I reached the per-run limit" text meant for a user who did ask.
        """
        executor = _CountingExecutor(
            script=[(SILENCE, []), (SUMMARY, [])],
            max_turns=1,
            allow_empty_response=True,
        )

        response = executor.run_stream("notify me only if the price drops")

        self.assertEqual(response, SILENCE)
        self.assertEqual(executor.calls, 1)


if __name__ == "__main__":
    unittest.main()
