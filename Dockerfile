FROM mcr.microsoft.com/devcontainers/python:2-3.14-trixie

ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock* ./
COPY . .

# Install uv and sync dependencies (no dev/tool deps)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN uv sync --no-dev

# Run main.py
CMD ["uv", "run", "python", "main.py"]



