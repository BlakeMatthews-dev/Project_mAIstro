"""Configuration for the Chaos Skill containing possible actions and their parameters."""

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
        "parameters": None
    },
    {
        "name": "rock_paper_scissors",
        "probability": 0.2,
        "description": "Play a game of rock-paper-scissors",
        "parameters": None
    },
    {
        "name": "random_sound",
        "probability": 0.15,
        "description": "Make a random sound effect",
        "parameters": None
    },
    {
        "name": "silly_story",
        "probability": 0.1,
        "description": "Tell a very short silly story",
        "parameters": None
    }
]
```