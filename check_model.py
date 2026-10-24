"""Check your credentials with one message: API_KEY=... BASE_URL=... MODEL=... python check_model.py"""
import os
import sys

import openai

client = openai.OpenAI(
    api_key="sk-FHD0uNiADcWueAHcYfs6lQ",
    base_url="https://litellm-hackathon.penpencil.guru"
)
response = client.chat.completions.create(
    model="gpt-6-luna",
    messages=[{"role": "user", "content": "Hi, How are you?"}],
)
print(response)
sys.exit(0)
