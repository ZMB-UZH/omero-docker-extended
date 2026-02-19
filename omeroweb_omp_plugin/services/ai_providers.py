AI_PROVIDER_OPTIONS = [
    {"value": "local", "label": "Local"},
    {"value": "groq", "label": "Groq"},
    {"value": "gemini", "label": "Gemini"},
    {"value": "claude", "label": "Claude"},
    {"value": "perplexity", "label": "Perplexity"},
    {"value": "xai", "label": "xAI"},
    {"value": "cohere", "label": "Cohere"},
]


def list_ai_provider_options():
    return list(AI_PROVIDER_OPTIONS)
