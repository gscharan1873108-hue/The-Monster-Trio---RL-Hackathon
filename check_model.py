"""Check your credentials with one message: API_KEY=... BASE_URL=... MODEL=... python check_model.py"""
import os
import sys

import openai

if os.path.exists(".env"):  # same file docker compose reads; real environment variables win
    for line in open(".env", encoding="utf-8"):
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#") and value:
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

client = openai.OpenAI(api_key=os.environ["API_KEY"], base_url=os.environ.get("BASE_URL") or None)
response = client.chat.completions.create(
    model=os.environ["MODEL"],
    messages=[{"role": "user", "content": "Hi, How are you?"}],
)
print(response)
sys.exit(0)
