# Chaos Skill

The Chaos Skill is a fun, unpredictable skill that agents can use to entertain users with random actions like dad jokes, silly poems, or playful interactions.

## Overview

The Chaos Skill randomly selects from a pool of entertaining actions based on configured probabilities. It's designed purely for amusement and can be assigned to agents by the conductor.

## Configuration

The Chaos Skill is configured in `src/maistro/skills/chaos_config.py`:

```python
# List of possible chaos actions with their probabilities and parameters
CHAOS_ACTIONS = [
    {
        "name": "dad_joke",
        "probability": 0.3,
        "description": "Tell a random dad joke",
        "parameters": None
    },
    {
        "name": "silly_poem",
        "probability": 0.25,
        "description": "Generate a short silly poem",
        "parameters": {
            "style": "optional style override",
            "lines": "optional line count"
        }
    },
    {
        "name": "rock_paper_scissors",
        "probability": 0.2,
        "description": "Play a round of rock-paper-scissors",
        "parameters": {
            "choice": "optional player choice override"
        }
    },
    {
        "name": "sound_effect",
        "probability": 0.15,
        "description": "Play a random sound effect",
        "parameters": None
    },
    {
        "name": "random_fact",
        "probability": 0.1,
        "description": "Share a random fun fact",
        "parameters": None
    }
]
```

## Usage Examples

### Assigning the Chaos Skill to an Agent

```python
from maistro.skills.chaos_skill import ChaosSkill
from maistro.skills.chaos_config import CHAOS_ACTIONS

# Create the skill with default configuration
chaos = ChaosSkill(CHAOS_ACTIONS)

# Assign to an agent for 5 minutes
agent.assign_skill(chaos, duration=300)
```

### Example Agent Interaction

```
User: What can you do?
Agent: I can tell you jokes, play games, or share silly poems! Want to see what happens?

*Agent randomly selects "dad_joke"*

Agent: Why don't scientists trust atoms? Because they make up everything!
```

### Programmatic Usage

```python
# Trigger a specific chaos action
chaos.perform_action("silly_poem", lines=4)

# Get a random action suggestion
action = chaos.get_random_action()
print(f"Next chaos action: {action['name']}")
```

## Skill Parameters

- **duration**: How long (in seconds) the skill should remain active
- **action_override**: Optional specific action to force instead of random selection
- **params**: Additional parameters passed to the selected action

## Logging

All Chaos Skill actions are logged in `src/maistro/skills/chaos_logger.py` with timestamps and outcomes.

## Customization

To add new actions:

1. Add a new entry to `CHAOS_ACTIONS` in `chaos_config.py`
2. Implement the action handler in `chaos_skill.py`
3. The action will be automatically included in random selections based on its probability

## Notes

- The Chaos Skill is designed for entertainment only
- Probabilities can be adjusted in the configuration
- Actions are selected randomly based on their configured weights
- The skill automatically handles invalid action requests gracefully

```

```
