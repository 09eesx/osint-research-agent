"""
OSINT Agent - Hızlı Test Modası
================================

Derinlik: 1 (sadece seed query + 1 seviye reasoning)
Amacı: Azure setup'ın çalışıp çalışmadığını hızlıca kontrol etmek
"""

import os
import json
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.azure import AzureOpenAI

load_dotenv()

# Azure model
def get_model():
    return AzureOpenAI(
        id=os.environ.get("AZURE_OPENAI_GENERATIVE_MODEL_DEPLOYMENT_NAME", "gpt-5.2"),
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ.get("AZURE_OPENAI_GENERATIVE_MODEL_DEPLOYMENT_NAME", "gpt-5.2"),
    )

# Simple discovery agent
discovery = Agent(
    name="Discovery",
    model=get_model(),
    tools=[],
    instructions=[
        "Verilen konuda kısa bir özet yap.",
        "3-4 cümlelik bilgi vermek yeterli.",
    ],
    markdown=False,
)

# Reasoning agent
reasoning = Agent(
    name="Reasoning",
    model=get_model(),
    instructions=[
        "Gelen bilgiye dayalı olarak 2-3 yeni araştırma görevini JSON formatında öner.",
        'Çıktı: {"tasks": ["görev1", "görev2"], "confidence": 0.8}',
    ],
    markdown=False,
)

if __name__ == "__main__":
    print("=" * 60)
    print("OSINT AGENT - QUICK TEST")
    print("=" * 60)
    
    query = "Guido van Rossum Python yaratıcısı"
    print(f"\n📌 Query: {query}\n")
    
    # Step 1: Discovery
    print("[1/2] Discovery Agent çalışıyor...")
    result1 = discovery.run(query)
    discovery_text = result1.content if hasattr(result1, "content") else str(result1)
    print(f"✓ Buldu:\n  {discovery_text[:200]}...\n")
    
    # Step 2: Reasoning
    print("[2/2] Reasoning Agent çalışıyor...")
    result2 = reasoning.run(f"Bulduğum bilgi: {discovery_text[:300]}")
    reasoning_text = result2.content if hasattr(result2, "content") else str(result2)
    print(f"✓ Öneriler:\n  {reasoning_text[:300]}...\n")
    
    print("=" * 60)
    print("✓ TEST BAŞARILI - Sistem çalışıyor!")
    print("=" * 60)
