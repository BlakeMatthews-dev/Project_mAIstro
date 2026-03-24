"""Logging module for Chaos Skill to track action usage and outcomes."""

import logging
from typing import Optional

# Configure logger for Chaos Skill
chaos_logger = logging.getLogger("chaos_skill")
chaos_logger.setLevel(logging.INFO)

# Create console handler
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# Create formatter and add it to the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)

# Add handler to the logger
chaos_logger.addHandler(ch)

def log_chaos_action(action_name: str, parameters: Optional[dict] = None, result: Optional[str] = None) -> None:
    """Log a Chaos Skill action with its parameters and result.

    Args:
        action_name: Name of the chaos action that was triggered
        parameters: Optional parameters passed to the action
        result: Optional result string from the action execution
    """
    log_data = {
        "action": action_name,
        "parameters": parameters or {},
        "result": result
    }
    chaos_logger.info(f"Chaos action triggered: {log_data}")
```