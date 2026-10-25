"""Check your credentials with one message: API_KEY=... BASE_URL=... MODEL=... python check_model.py"""
import os
import sys

import openai

client = openai.OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL")
)
response = client.chat.completions.create(
    model=os.getenv("MODEL"),
    messages=[{"role": "user", "content": "Hi, How are you?"}],
)
print(response)
sys.exit(0)
