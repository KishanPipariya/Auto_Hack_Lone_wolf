# Use uv base image for fast python management
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Set working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first to leverage cache
COPY pyproject.toml uv.lock ./

# Install dependencies (without installing the project itself yet)
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
COPY . .

# Install the project
RUN uv sync --frozen --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Expose the port
EXPOSE 8000

# Run the application
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
