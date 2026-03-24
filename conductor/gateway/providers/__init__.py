"""Inference providers — abstracts local llama-server vs. cloud API backends."""

from .base import CompletionResult, InferenceProvider
from .factory import create_provider

__all__ = ["InferenceProvider", "CompletionResult", "create_provider"]
