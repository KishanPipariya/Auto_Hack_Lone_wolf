# Travel Planner Agent ✈️

A smart AI-powered travel agent that creates personalized itineraries using Gemini 2.0.

## Prerequisites

- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** (Fast Python package installer and resolver)
  ```bash
  # Install uv if you haven't already
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Gemini API Key**: Get one from [Google AI Studio](https://aistudio.google.com/).

## Installation

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone https://github.com/KishanPipariya/Auto_Hack_Lone_wolf
    cd Auto_Hack_Lone_wolf
    ```

2.  **Install dependencies**:
    ```bash
    uv sync
    ```

## Configuration

1.  **Environment Variables**:
    Create a `.env` file in the root directory. You can use `.env.template` as a reference.

    ```bash
    cp .env.template .env
    ```

2.  **Edit `.env`**:
    Open `.env` and add your API keys:
    ```env
    GOOGLE_API_KEY=your_gemini_api_key_here
    # Optional: For fallback models
    OPENROUTER_API_KEY=your_openrouter_key_here
    ```

## Running the Application

Start the backend server with hot-reloading:

```bash
uv run uvicorn fast_api_server:app --reload --host 127.0.0.1 --port 8000
```

Once running, open your browser and go to:
👉 **[http://localhost:8000/](http://localhost:8000/)**

## Features

- **AI Trip Planning**: Generates detailed day-by-day itineraries based on city, budget, and interests.
- **Dynamic Photos**: Automatically finds relevant photos for every activity.
- **Real-time Streaming**: Watch the plan being generated step-by-step.
- **Responsive UI**: Works great on mobile and desktop.
- **Dark Mode**: Toggle between light and dark themes.

## Development

- **Run Tests**:
  ```bash
  uv run pytest
  ```
