# OSINT Agents - Güncelleme Özeti

## ✅ Tamamlanan Iyileştirmeler

### 1. **Checkpoint / Resume Desteği**
- Her 5 görevde bir durumu `output/progress_<query_name>.json`'a kaydediyor
- Kesinti (Ctrl+C) sonrası `--resume` flag'ı ile kalınan yerden devam edebiliyor
- Atomik yazma (temp dosya + `os.replace()`) ile yarım kalmış dosya sorununu önlüyor

**Kullanım:**
```bash
python osint_agents.py "Esma Cerit"              # ilk çalıştırma
python osint_agents.py "Esma Cerit" --resume     # checkpoint'ten devam
```

### 2. **Rate Limiting (GitHub API)**
- GitHub Search API çağrıları arasında 2.5 + 0-0.3 sn random gecikme
- GitHub Core API çağrıları arasında 0.5 + 0-0.3 sn random gecikme
- `X-RateLimit-Remaining` ve `X-RateLimit-Resource` header'larını okuyup bucket bazlı uyarı veriyor
- Search ve Core API limitleri farklı olduğu için ayrı throttle uygulanıyor

### 3. **Görev Kalitesi Kontrolleri**
- Low-signal görevler (`Wikipedia REST API`, `maxlag`, `etiquette` gibi) erken eleniyor
- Benzer görevler normalize edilip duplicate olarak birleştiriliyor
- Yeni görevler priority score ile sıraya alınıyor; daha alakalı ve sığ görevler önce çalışıyor
- Her adımda en fazla 5 yeni görev kuyruğa ekleniyor
- `--max-tasks` ile task explosion için basit bütçe limiti var
- `--max-tasks-per-entity` ile aynı entity etrafında gereksiz tekrar aramalar kesiliyor
- URL overlap %90+ ise ve yeni entity/relation çıkmıyorsa marginal gain düşük sayılıp genişleme duruyor

### 4. **Entity/Relation Graph Çıkarımı**
- Araştırma çıktıları artık ham görev cümlesi olarak node'a yazılmıyor
- Ayrı bir extraction agent, gerçek entity'leri (`person`, `company`, `repository` vb.) ve ilişkileri (`WORKS_AT`, `FOUNDED`, `MAINTAINS` vb.) JSON olarak çıkarıyor
- `graph.add_edge()` artık gerçek ilişkiler için kullanılıyor; `edges` boş kalmamalı
- Kanıtsız veya recruiter scope dışı ilişkiler graph'a yazılmıyor
- Her edge artık `source_type`, `evidence_snippet`, `needs_review`, `retrieved_at` alanlarıyla geliyor
- Her edge ayrıca `source_tier`, `source_tier_weight`, `llm_confidence`, `final_score`, `evidence_span` alanlarını taşıyor
- Kaynak tipi puanlanıyor; düşük kaliteli veya zayıf güvenli edge'ler otomatik olarak review gerektiriyor
- Aynı entity farklı adlarla gelirse canonical node altında birleştiriliyor (`aliases`)
- Aynı relation birden fazla bağımsız kaynakla gelirse `corroborated_by` artıyor ve `needs_review` düşebiliyor

**Log çıktısı:**
```
⚠️ GitHub rate limit azaldı: 15 istek kaldı
```

### 5. **File Logging (Termin + Dosya)**
- Hem `output/osint_run.log`'a hem terminale yazıyor
- tmux'ta çalıştırınca terminal kapansa bile log kalıyor
- Severity seviyeleri (INFO, WARNING, ERROR) ile ayırım yapıyor

**Örnek:**
```
2026-07-06 12:34:56,123 [INFO] 🚀 Yeni araştırma başlatılıyor: Esma Cerit
2026-07-06 12:34:58,456 [WARNING] ⚠️ GitHub rate limit azaldı: 150 istek kaldı
```

### 6. **Crawl4AI Tool'u (Discovery Agent'a eklendi)**
- `fetch_web_page_markdown()`: Genel web sayfalarını (haber, blog, şirket sayfası) temiz markdown'a çevirme
- GitHub/Wikipedia API'si olmayan kaynaklar için
- JS-render gerektiren sayfalar da çalışıyor

**Fonksiyon imzası:**
```python
def fetch_web_page_markdown(url: str) -> str
    # -> {"found": True, "url": "...", "content": "..."}
```

### 7. **CLI Parametreleri (argparse)**
```bash
python osint_agents.py --help

positional arguments:
  seed_query            Araştırmaya başlanacak kişi/kurum adı (default: "Esma Cerit")

optional arguments:
  --resume              Önceki checkpoint'ten devam et
  --max-depth N         Maksimum araştırma derinliği (default: 3)
  --max-tasks N         İşlenecek maksimum görev sayısı (default: 25)
  --max-tasks-per-entity N  Aynı entity için işlenecek maksimum görev sayısı (default: 4)
```

## 📊 Mimari Değişiklikler

### Orchestrator
```
run_research()
├── checkpoint_path = output/progress_<query>.json
├── Load checkpoint (--resume ise)
│   ├── graph.nodes, graph.edges
│   ├── task_queue
│   └── seen_tasks
├── While task_queue:
│   ├── Depth/duplication kontrolü
│   ├── Agent çalıştır (Discovery/GitHub/Web)
│   ├── Reasoning agent'a yeni görevleri sor
│   ├── Queue'ya ekle (depth + 1)
│   └── Her 5 görevde checkpoint kaydet
├── KeyboardInterrupt -> checkpoint kaydet + çık
└── Başarı -> checkpoint sil + return graph
```

## 🔧 Dependency Eklemeler

```
pip install crawl4ai python-dotenv
```

**crawl4ai'nin kendi dependencies'leri:**
- playwright, patchright (browser automation)
- lxml, brotli (HTML parsing & compression)
- numpy, pillow (image processing)

## 📁 Yeni Dosyalar

- `output/osint_run.log` — tüm log'lar buraya
- `output/progress_<query>.json` — kesinti durumunda checkpoint
- `output/knowledge_graph.json` — araştırma sonucu

## 🧪 Test Edecek Şeyler

1. **Basit çalıştırma (derinlik=1)**
   ```bash
   python osint_agents.py "Test" --max-depth 1
   ```

2. **Checkpoint test** (Ctrl+C > --resume)
   ```bash
   python osint_agents.py "Esma Cerit"
   # 5 saniye sonra Ctrl+C
   python osint_agents.py "Esma Cerit" --resume
   ```

3. **Log çıktısı**
   ```bash
   tail -f output/osint_run.log
   ```

4. **Crawl4AI test** (genel web sayfası)
   - Discovery agent'a haber sitesi URL'i geçmek
   - Markdown çıktısını doğrula

## ⚠️ Dikkat Edilecek Noktalar

- Crawl4AI browserless değil — Playwright kullanıyor (ilk kurulumda Playwright browser'ı indiriyor, 100MB+)
- Derinlik arttıkça LLM çağrıları da artar (maliyet!)
- `GITHUB_TOKEN` yoksa script başlangıçta uyarı loglar ve GitHub Search API çok daha düşük limite düşer
- GitHub Search API: authenticated 30/dakika, unauthenticated 10/dakika
- GitHub Core API: authenticated 5000/saat
- crawl4ai opsiyonel — olmasa da Discovery agent devam çalışır (sadece web_page çağrısı fail olur)
