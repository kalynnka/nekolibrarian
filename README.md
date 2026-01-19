# Neko Librarian

A QQ bot powered by NapCat and AI agents (pydantic-ai).

## Prerequisites

Before running the bot, you need to set up the following:

### NapCat

Set up [NapCat](https://napneko.github.io/) as the QQ protocol adapter. Refer to the official documentation for installation and configuration.

### LLM API Keys

Create a `.env` file in the project root with your API keys:

```env
GOOGLE_API_KEY=your_gemini_api_key_here
```

Get your Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

### Tools (Optional)

The bot supports optional tools that require additional configuration:

- **Pixiv**: Set `PIXIV_REFRESH_TOKEN` in `.env`. See [pixivpy](https://github.com/upbit/pixivpy) for how to obtain the refresh token.
- **QWeather**: Set `QWEATHER_KEY_ID`, `QWEATHER_PROJECT_ID` and provide the Ed25519 private key. See [QWeather Dev](https://dev.qweather.com/) for API registration.

## Running in a Dev Container

1. Open the project in VS Code with the Dev Containers extension installed
2. When prompted, click "Reopen in Container" (or use the command palette: `Dev Containers: Reopen in Container`)
3. Once the container is built and running, install dependencies with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

4. Run the bot:

```bash
python main.py
```

The bot will start and connect to the configured NapCat instance.

### Running with Debugger

A VS Code launch configuration is already set up. To run with the debugger:

1. Open the Run and Debug panel (`Ctrl+Shift+D` / `Cmd+Shift+D`)
2. Select **"Python Debugger: NCatBot"** from the dropdown
3. Press `F5` or click the green play button

This configuration uses `watchfiles` to automatically reload the bot when you make changes to Python files in `main.py` or the `app/` directory.

Alternatively, use **"Python Debugger: Current File"** to debug any individual Python file.

## Project Structure

```
├── main.py                 # Entry point - bot initialization and event handlers
├── config.yaml             # Bot configuration file
├── app/
│   ├── agents/             # AI agents powered by pydantic-ai
│   │   ├── group.py        # Group chat agent with system prompts
│   │   ├── private.py      # Private message agent
│   │   └── deps.py         # Dependency injection for agents
│   ├── tools/              # Agent tools
│   │   ├── memory.py       # Message persistence tool
│   │   ├── pixiv.py        # Pixiv image search tool
│   │   └── qweather.py     # Weather query tool
│   ├── configs.py          # Configuration models (Pydantic settings)
│   ├── database.py         # SQLAlchemy async database setup
│   ├── models.py           # ORM models (messages, etc.)
│   ├── schemas.py          # Pydantic schemas for data transfer
│   └── collector.py        # Message batching handler
├── alembic/                # Database migrations
├── data/                   # Plugin configurations and RBAC
├── napcat/                 # NapCat runtime configuration
└── miapi/                  # MiHome device API specs
```

### Key Components

- **Agents** (`app/agents/`): AI chat agents using [pydantic-ai](https://ai.pydantic.dev/) with Gemini models. Each agent has a system prompt and can use tools.
- **Tools** (`app/tools/`): Capabilities exposed to agents - weather lookups, Pixiv searches, memory persistence.
- **Collector** (`app/collector.py`): Batches rapid incoming messages before processing to reduce API calls.
- **Database** (`app/database.py`, `app/models.py`): PostgreSQL storage for chat history using SQLAlchemy async.