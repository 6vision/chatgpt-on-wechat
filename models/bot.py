"""
Auto-replay chat robot abstract class
"""

from bridge.context import Context
from bridge.reply import Reply


def read_error_body(response) -> dict:
    """Return the ``error`` object of a failed HTTP response as a dict.

    Never raises: a non-JSON body or a missing / non-object ``error`` becomes
    ``{"message": ...}``.
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        error = {"message": error or response.text[:300]}
    return error


class Bot(object):
    """
    Base class for all chat-bot implementations.

    Subclasses may also implement:

        call_with_tools(messages, tools=None, stream=False, **kwargs)
            -> dict | generator  (OpenAI-compatible format)

        call_vision(image_url, question, model=None, max_tokens=1000)
            -> dict with keys: model, content, usage  (or error/message)

    These are NOT defined here to avoid shadowing concrete implementations
    provided by mixin classes (e.g. OpenAICompatibleBot) in the MRO.
    Use ``hasattr(bot, 'call_vision')`` to detect support at runtime.
    """

    def reply(self, query, context: Context = None) -> Reply:
        """
        bot auto-reply content
        :param req: received message
        :return: reply content
        """
        raise NotImplementedError
