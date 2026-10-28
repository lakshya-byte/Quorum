"""List Nemotron models on Nebius Token Factory and ask one to say hello."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402
from app.llm import chat, make_client  # noqa: E402


async def main() -> None:
    settings = load_settings()
    if not settings.nebius_api_key:
        sys.exit("NEBIUS_API_KEY is not set")
    client = make_client(settings.nebius_api_key)
    models = [m.id async for m in client.models.list() if "nemotron" in m.id.lower()]
    print("Nemotron models:")
    for model_id in models:
        print(" -", model_id)
    model = settings.model_nano or (models[0] if models else "")
    if not model:
        sys.exit("no model available")
    reply, usage = await chat(client, model, "You are friendly and brief.", "Say hello in one sentence.")
    print(f"\n{model} says: {reply.strip()}\nusage: {usage}")


if __name__ == "__main__":
    asyncio.run(main())
