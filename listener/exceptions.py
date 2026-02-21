
from __future__ import annotations


class ListenerError(Exception):

    pass


class SummarizationInProgressError(Exception):

    def __init__(self, message: str = "Summarization in progress, please try again later"):
        self.message = message
        super().__init__(self.message)
