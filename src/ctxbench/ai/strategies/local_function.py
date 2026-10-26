"""Local function transport using the shared client tool loop."""
from ctxbench.ai.strategies.client_tools import ClientToolStrategy, DEFAULT_OPERATION_SYSTEM_INSTRUCTION


class LocalFunctionStrategy(ClientToolStrategy):
    label = "Local function"
