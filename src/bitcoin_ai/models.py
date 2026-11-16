from typing import Protocol


class TextModel(Protocol):
    """Interface for a future local/open-weight language model."""

    def generate(self, prompt: str) -> str:
        ...


class NoModelConfigured:
    """Explicit placeholder; prevents silently pretending a model is running."""

    def generate(self, prompt: str) -> str:
        raise RuntimeError(
            "No language model is configured. The current baseline uses "
            "retrieval and cited source excerpts, not generative inference."
        )
