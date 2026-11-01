# Octopus — OSINT Research Agent

Verilen bir ad veya konu için açık kaynaklardan (web, GitHub, Wikipedia) bilgi toplayıp, bulunanlardan yeni araştırma görevleri türeten çoklu ajanlı bir araştırma prototipi.

## Mimari

| Bileşen | Görev |
| --- | --- |
| Discovery Agent | Web, GitHub, Wikipedia ve genel sayfalarda arama (Crawl4AI) |
| GitHub Agent | Profil ve repo detaylarını çıkarır |
| Reasoning Agent | Bulunanlardan yeni görevler türetir (JSON) |
| Orchestrator | Görev kuyruğunu derinlik limiti ve checkpoint desteğiyle işler |

Ajanlar [Agno](https://github.com/agno-agi/agno) ve Azure OpenAI ile çalışır. Ayrıntılı davranış notları (checkpoint/resume, rate limiting, görev kalite kontrolleri) için [UPDATES.md](UPDATES.md) dosyasına bakın.

## Kurulum

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install agno openai anthropic azure-ai-inference requests python-dotenv crawl4ai fastapi uvicorn
cp .env.example .env   # değerleri doldurun
```

`.env` dosyası repoya dahil değildir. Gerekli değişkenler `.env.example` içindedir.

## Kullanım

```bash
python osint_agents.py "Araştırılacak konu"
python osint_agents.py "Araştırılacak konu" --resume
python osint_agents.py "Araştırılacak konu" --max-depth 2
```

Web arayüzü için:

```bash
uvicorn fastapi_app:app --reload
```

Uç noktalar: `GET /`, `GET /health`, `POST /api/search`, `POST /search`. Ayrı bir React arayüz denemesi `web/` klasöründedir (`npm i && npm run dev`).

## Sorumlu kullanım

Bu araç yalnızca herkese açık kaynakları tarar. Başkaları hakkında profil çıkarmak için kullanmayın; ilgili sitelerin kullanım koşullarına ve KVKK/GDPR gibi veri koruma mevzuatına uyun.
