# from google.genai.types import ThinkingConfigDict
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

# Create a simple chat agent using Gemini
# Set GEMINI_API_KEY environment variable for authentication
chat = Agent(
    model="gemini-3-flash-preview",
    system_prompt="You are a helpful assistant. Be concise and friendly.",
    model_settings=GoogleModelSettings(
        temperature=0.6,
        # google_thinking_config=ThinkingConfigDict(
        #     thinking_budget=1024,
        # ),
    ),
)
