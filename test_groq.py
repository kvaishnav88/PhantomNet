import os, time
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])

start = time.perf_counter()
response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
    max_tokens=300,
    reasoning_effort="low",
)
elapsed = (time.perf_counter() - start) * 1000

msg = response.choices[0].message
print("CONTENT:", repr(msg.content))
print("FINISH:", response.choices[0].finish_reason)
print("USAGE:", response.usage)
print(f"Latency: {elapsed:.0f} ms")
