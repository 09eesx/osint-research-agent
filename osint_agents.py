"""
OSINT Araştırma Ajanı - Üretim Prototipi
=========================================

Kurulum:
    uv venv --python 3.12
    source .venv/bin/activate
    
    # NOT: agno.models.azure import ederken anthropic ve azure-ai-inference
    # paketlerini de arıyor (bilinen kusur, agno-agi/agno #2371)
    uv pip install agno openai anthropic azure-ai-inference requests python-dotenv crawl4ai

.env dosyasında gerekli:
    AZURE_OPENAI_API_KEY=<token>
    AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_VERSION=2024-12-01-preview
    AZURE_OPENAI_GENERATIVE_MODEL_DEPLOYMENT_NAME=gpt-5.2
    GITHUB_TOKEN=<optional - rate limit kontrol için>

Kullanım:
    python osint_agents.py "Esma Cerit"                 # ilk çalıştırma
    python osint_agents.py "Esma Cerit" --resume        # checkpoint'ten devam
    python osint_agents.py "Esma Cerit" --max-depth 2   # derinliği sınırla

Checkpoint/Resume:
    Araya gelen kesimde (Ctrl+C) durumu output/progress_<name>.json'a kaydediyor.
    Tekrar --resume ile çalıştırdığında kalınan yerden devam ediyor.

Mimari:
    Discovery Agent    -> Web, GitHub, Wikipedia, genel sayfalar (Crawl4AI)
    GitHub Agent       -> GitHub profil & repo detayları
    Reasoning Agent    -> Bulunandan yeni görevler türetir (JSON)
    Orchestrator       -> Görev kuyruğunu derinlik limitiyle + checkpoint desteğiyle işler
"""

import os
import json
import sys
import time
import random
import logging
import argparse
import requests
import re
import heapq
import itertools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)  # .env dosyasını script klasöründen yükle

from agno.agent import Agent
from agno.models.azure import AzureOpenAI

# ---------------------------------------------------------------------------
# 0. LOGGING - terminale ve dosyaya
# ---------------------------------------------------------------------------

os.makedirs("output", exist_ok=True)

# Windows encoding hatası fix'i - emoji'leri kaldır
import io
if sys.platform == "win32":
    import codecs
    # Windows terminal'de UTF-8 desteği
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/osint_run.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("osint")

# ---------------------------------------------------------------------------
# 1. ARAÇLAR (Tools) - basit Python fonksiyonları, Agno'ya doğrudan verilebilir
# ---------------------------------------------------------------------------

GITHUB_CORE_MIN_DELAY = 0.5
GITHUB_SEARCH_MIN_DELAY = 2.5
BLOCK_INDICATOR_PATTERNS = [
    "akamai",
    "access denied",
    "forbidden",
    "bot detection",
    "captcha",
    "security check",
    "rate limit exceeded",
]
RELATION_SIGNAL_PATTERNS = [
    " ceo ",
    " founder ",
    " co-founder ",
    " works at ",
    " joined ",
    " board ",
    " management ",
    " leadership ",
    " maintainer ",
    " repository ",
    " github ",
    " company ",
    " organization ",
]


def _mask_token(token: str) -> str:
    """Log için token'ın küçük bir kısmını göster."""
    token = token.strip()
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _github_token() -> str:
    """Token'ı normalize ederek döndür."""
    return os.environ.get("GITHUB_TOKEN", "").strip()


def _github_headers() -> Dict[str, str]:
    """GitHub token'ı varsa header'a ekle."""
    token = _github_token()
    if token:
        return {"Authorization": f"token {token}"}
    return {}


def _github_delay(api_type: str) -> None:
    """GitHub API tipine göre güvenli throttle uygula."""
    base_delay = GITHUB_SEARCH_MIN_DELAY if api_type == "search" else GITHUB_CORE_MIN_DELAY
    time.sleep(base_delay + random.uniform(0, 0.3))


def _log_github_rate_limit(resp: requests.Response) -> None:
    """GitHub rate limit durumunu endpoint tipine göre logla."""
    remaining = resp.headers.get("X-RateLimit-Remaining")
    resource = resp.headers.get("X-RateLimit-Resource", "unknown")
    limit = resp.headers.get("X-RateLimit-Limit", "?")
    token_loaded = bool(_github_token())

    if remaining is None:
        return

    try:
        remaining_value = int(remaining)
    except ValueError:
        return

    if resource == "search":
        threshold = 10 if token_loaded else 5
    else:
        threshold = 200

    if remaining_value < threshold:
        logger.warning(
            f"GitHub {resource} rate limit azaldi: {remaining}/{limit} istek kaldi"
        )


def _log_github_auth_status() -> None:
    """GitHub token durumunu başlangıçta açıkça göster."""
    token = _github_token()
    if token:
        logger.info(f"GitHub token yuklendi ({_mask_token(token)})")
    else:
        logger.warning(f"GITHUB_TOKEN bulunamadi: {ENV_PATH}")


_log_github_auth_status()


def github_search_user(query: str) -> str:
    """GitHub'da kullanıcı adı veya isimle arama yapar, ilk sonuçları döner."""
    _github_delay("search")
    
    try:
        resp = requests.get(
            "https://api.github.com/search/users",
            params={"q": query},
            headers=_github_headers(),
            timeout=10,
        )
        
        _log_github_rate_limit(resp)
        
        resp.raise_for_status()
        items = resp.json().get("items", [])[:5]
        return json.dumps([{"login": i["login"], "url": i["html_url"]} for i in items])
    except Exception as e:
        logger.error(f"github_search_user hatası: {e}")
        return json.dumps({"error": str(e)})


def github_user_profile(username: str) -> str:
    """Belirli bir GitHub kullanıcısının profil ve repo bilgilerini döner."""
    _github_delay("core")
    
    try:
        profile = requests.get(
            f"https://api.github.com/users/{username}", 
            headers=_github_headers(), 
            timeout=10
        )
        _log_github_rate_limit(profile)
        profile.raise_for_status()
        profile_data = profile.json()
        
        _github_delay("core")
        
        repos = requests.get(
            f"https://api.github.com/users/{username}/repos",
            params={"sort": "updated", "per_page": 10},
            headers=_github_headers(),
            timeout=10,
        )
        _log_github_rate_limit(repos)
        repos.raise_for_status()
        repos_data = repos.json()
        
        return json.dumps({
            "name": profile_data.get("name"),
            "company": profile_data.get("company"),
            "bio": profile_data.get("bio"),
            "blog": profile_data.get("blog"),
            "repos": [
                {
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "language": r.get("language"),
                    "stars": r.get("stargazers_count"),
                }
                for r in repos_data
                if isinstance(r, dict)
            ],
        })
    except Exception as e:
        logger.error(f"github_user_profile hatası: {e}")
        return json.dumps({"error": str(e)})


def wikipedia_summary(title: str) -> str:
    """Wikipedia'dan bir konu/kurum/kişi özeti çeker."""
    try:
        resp = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}", 
            timeout=10
        )
        
        if resp.status_code != 200:
            return json.dumps({"found": False})
        
        data = resp.json()
        return json.dumps({"found": True, "extract": data.get("extract", "")})
    except Exception as e:
        logger.error(f"wikipedia_summary hatası: {e}")
        return json.dumps({"found": False, "error": str(e)})


def fetch_web_page_markdown(url: str) -> str:
    """Crawl4AI ile genel web sayfasını temiz markdown olarak çeker.
    GitHub/Wikipedia API'si olmayan sayfalar için (haber, blog, şirket sayfası vb.)"""
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

        async def _crawl():
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000)
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)
                return result.markdown if result.success else None

        def _run_in_new_loop() -> Optional[str]:
            return asyncio.run(_crawl())

        try:
            asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                markdown = executor.submit(_run_in_new_loop).result()
        except RuntimeError:
            markdown = asyncio.run(_crawl())
        
        if markdown is None:
            return json.dumps({"found": False, "url": url})
        
        # İlk 5000 karakteri al
        return json.dumps({"found": True, "url": url, "content": markdown[:5000]})
    
    except ImportError:
        logger.warning("⚠️ crawl4ai kurulu değil - 'pip install crawl4ai' ile ekle")
        return json.dumps({"found": False, "error": "crawl4ai_not_installed"})
    except Exception as e:
        logger.error(f"fetch_web_page_markdown hatası: {e}")
        return json.dumps({"found": False, "error": str(e)})


# ---------------------------------------------------------------------------
# 2. AJANLAR
# ---------------------------------------------------------------------------

def get_azure_model(deployment_env_var: str = "AZURE_OPENAI_GENERATIVE_MODEL_DEPLOYMENT_NAME") -> AzureOpenAI:
    """Her ajan için ayrı model instance'i."""

    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    deployment = os.environ.get(
        deployment_env_var,
        os.environ.get("AZURE_OPENAI_GENERATIVE_MODEL_DEPLOYMENT_NAME", "gpt-5.2"),
    )
    
    if not api_key or not endpoint:
        raise ValueError("AZURE_OPENAI_API_KEY ve AZURE_OPENAI_ENDPOINT env variables gerekli")
    
    return AzureOpenAI(
        id=deployment,
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
        azure_deployment=deployment,
    )


discovery_agent = Agent(
    name="DiscoveryAgent",
    model=get_azure_model("AZURE_OPENAI_DISCOVERY_MODEL_DEPLOYMENT_NAME"),
    tools=[github_search_user, wikipedia_summary, fetch_web_page_markdown],
    instructions=[
        "Verilen isim/şirket için ilk kaynakları bul.",
        "GitHub, Wikipedia, ve genel web sayfalarını araştır.",
        "Sadece herkese açık, yasal erişilebilir kaynakları kullan.",
        "Bulduğun her bilgi için kaynağı (URL) belirt.",
    ],
    markdown=False,
)

github_agent = Agent(
    name="GitHubAgent",
    model=get_azure_model("AZURE_OPENAI_GITHUB_MODEL_DEPLOYMENT_NAME"),
    tools=[github_user_profile],
    instructions=[
        "Verilen GitHub kullanıcı adı için profil ve repo bilgisi çıkar.",
        "Kullanılan teknolojileri, öne çıkan repoları ve olası bağlı organizasyonları listele.",
    ],
    markdown=False,
)

reasoning_agent = Agent(
    name="ReasoningAgent",
    model=get_azure_model("AZURE_OPENAI_REASONING_MODEL_DEPLOYMENT_NAME"),
    instructions=[
        "Sana bir bilgi parçası verilecek (ör. 'X kişisi Y şirketinde çalışıyor').",
        "Bu sistem recruiter due-diligence amacıyla kullanılıyor; sadece profesyonel geçmiş, kamuya açık iş ilişkileri, resmi profiller, repo/geçmiş teknoloji sinyalleri gibi görevler üret.",
        "Bu bilgiden hangi YENİ araştırma görevlerinin türetilebileceğini düşün.",
        "Ana hedefle doğrudan ilişkili olmayan altyapı/dokümantasyon görevleri üretme.",
        "Wikipedia API, REST API, Query API, etiquette, maxlag gibi araştırma konusu olmayan görevleri dışla.",
        "Impersonation, sahte/klon hesap taraması, konuşma transkripti arşivleme, external links/reference harvesting, genel izleme/takip görevleri üretme.",
        "Bir adımda en fazla 5 yüksek değerli görev öner; benzer görevleri birleştir.",
        "SADECE aşağıdaki JSON şemasında cevap ver, başka hiçbir metin ekleme:",
        '{"new_tasks": [{"task": "...", "target_agent": "github|wikipedia|web", "reason": "..."}], "confidence": 0.0-1.0}',
        "Hassas veri kategorilerine (etnik köken, sağlık, siyasi görüş, din, sendika üyeliği) "
        "değinen görevler ASLA üretme; bunları filtrele.",
    ],
    markdown=False,
)

extraction_agent = Agent(
    name="ExtractionAgent",
    model=get_azure_model("AZURE_OPENAI_EXTRACTION_MODEL_DEPLOYMENT_NAME"),
    instructions=[
        "Sana araştırma çıktısı verilecek.",
        "Sadece recruiter due-diligence açısından anlamlı entity ve ilişkileri çıkar.",
        "Entity tipleri sadece şunlardan biri olsun: person, company, organization, repository, profile, project.",
        "İlişki tipleri kısa ve büyük harf snake_case olsun: WORKS_AT, FOUNDED, OWNS, MAINTAINS, CONTRIBUTES_TO, ASSOCIATED_WITH, HAS_PROFILE.",
        "Belirsiz veya kanıtsız ilişki üretme. Çıkaramıyorsan boş liste döndür.",
        "Task metnini node olarak yazma; sadece gerçek entity isimleri kullan.",
        "Sahte hesap, risk, transkript, external links, references, genel dedikodu veya hassas veri çıkarımı yapma.",
        "Her relation için mümkünse kısa bir evidence_span ver; span çıktının içindeki gerçek cümleye veya cümle parçasına yakın ve 240 karakterden kısa olsun.",
        "Her relation için source_name ve target_name alanlarını da doldur; bunlar ilgili entity isimleriyle aynı olsun.",
        "SADECE şu JSON şemasında cevap ver:",
        '{"entities":[{"id":"person_elon_musk","name":"Elon Musk","type":"person","source_url":""}],"relations":[{"source":"person_elon_musk","source_name":"Elon Musk","target":"company_tesla","target_name":"Tesla","relation":"WORKS_AT","confidence":0.82,"source_url":"","evidence_span":"Elon Musk is the CEO of Tesla."}]}',
    ],
    markdown=False,
)

fallback_reasoning_agent = Agent(
    name="FallbackReasoningAgent",
    model=get_azure_model("AZURE_OPENAI_REASONING_FALLBACK_MODEL_DEPLOYMENT_NAME"),
    instructions=reasoning_agent.instructions,
    markdown=False,
)

fallback_extraction_agent = Agent(
    name="FallbackExtractionAgent",
    model=get_azure_model("AZURE_OPENAI_EXTRACTION_FALLBACK_MODEL_DEPLOYMENT_NAME"),
    instructions=extraction_agent.instructions,
    markdown=False,
)


# ---------------------------------------------------------------------------
# 3. GRAPH (basit in-memory node-edge modeli; sonra Neo4j'ye yazılır)
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeGraph:
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(
        default_factory=lambda: {
            "partial_results": False,
            "warnings": [],
            "fallbacks_used": [],
            "rate_limit_hits": 0,
            "processed_tasks": 0,
        }
    )

    def _find_node_index(self, node_id: str) -> Optional[int]:
        for index, node in enumerate(self.nodes):
            if node["id"] == node_id:
                return index
        return None

    def find_entity_id(self, node_type: str, name: str) -> Optional[str]:
        normalized_name = _normalize_task_text(name)
        for node in self.nodes:
            if node.get("type") != node_type:
                continue
            aliases = node.get("aliases", [])
            candidate_names = [node.get("name", "")] + aliases
            if any(_normalize_task_text(candidate) == normalized_name for candidate in candidate_names):
                return node["id"]
        return None

    def add_node(self, node_id: str, node_type: str, name: str, source_url: str = "") -> str:
        existing_id = self.find_entity_id(node_type, name)
        if existing_id:
            existing_index = self._find_node_index(existing_id)
            if existing_index is not None:
                node = self.nodes[existing_index]
                aliases = set(node.get("aliases", []))
                if name and name != node.get("name"):
                    aliases.add(name)
                if aliases:
                    node["aliases"] = sorted(aliases)
                if source_url and not node.get("source_url"):
                    node["source_url"] = source_url
            return existing_id

        if self._find_node_index(node_id) is None:
            self.nodes.append(
                {
                    "id": node_id,
                    "type": node_type,
                    "name": name,
                    "source_url": source_url,
                    "aliases": [],
                }
            )
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        confidence: float,
        source_url: str = "",
        source_type: str = "unknown",
        source_tier: str = "unknown",
        source_tier_weight: float = 0.3,
        evidence_snippet: str = "",
        evidence_span: str = "",
        needs_review: bool = True,
        retrieved_at: str = "",
        corroborated_by: int = 1,
        llm_confidence: float = 0.0,
        final_score: float = 0.0,
    ):
        self.edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "confidence": confidence,
                "source_url": source_url,
                "source_type": source_type,
                "source_tier": source_tier,
                "source_tier_weight": source_tier_weight,
                "evidence_snippet": evidence_snippet,
                "evidence_span": evidence_span,
                "needs_review": needs_review,
                "retrieved_at": retrieved_at,
                "corroborated_by": corroborated_by,
                "llm_confidence": llm_confidence,
                "final_score": final_score,
            }
        )

    def to_json(self) -> str:
        return json.dumps(
            {"nodes": self.nodes, "edges": self.edges, "metadata": self.metadata},
            ensure_ascii=False,
            indent=2,
        )


# ---------------------------------------------------------------------------
# 4. ORKESTRASYON (derinlik limitli + checkpoint/resume)
# ---------------------------------------------------------------------------

MAX_DEPTH = 3
DEFAULT_MAX_TASKS = 25
DEFAULT_MAX_TASKS_PER_ENTITY = 4
MAX_NEW_TASKS_PER_STEP = 5
MARGINAL_GAIN_OVERLAP_THRESHOLD = 0.9
LOW_SIGNAL_PATTERNS = [
    "api",
    "rest api",
    "query api",
    "etiquette",
    "maxlag",
    "help:",
    "template:",
    "special:",
    "user talk:",
    "talk:",
    "category:",
]
SOURCE_TIERS = {
    "official_site": 1.0,
    "github.com": 0.9,
    "sec.gov": 1.0,
    "linkedin.com": 0.7,
    "crunchbase.com": 0.65,
    "medium.com": 0.4,
    "wikipedia.org": 0.5,
    "forum": 0.2,
    "blog_generic": 0.25,
    "web_generic": 0.35,
    "unknown": 0.3,
}
OFF_SCOPE_PATTERNS = [
    "impersonation",
    "fake account",
    "clone account",
    "sahte hesap",
    "klon hesap",
    "transcript",
    "tam transkript",
    "archive",
    "arsivle",
    "external links",
    "references",
    "reference section",
    "monitor",
    "izleme",
    "surveillance",
    "risk taramasi",
]

AGENT_MAP = {
    "github": github_agent,
    "wikipedia": discovery_agent,
    "web": discovery_agent,
}
TASK_QUEUE_SEQUENCE = itertools.count()


def _is_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return "429" in message or "rate limit" in message or "too_many_requests" in message


def _append_graph_warning(graph: "KnowledgeGraph", warning: str) -> None:
    warnings = graph.metadata.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)


def _run_agent_with_fallback(
    primary_agent: Agent,
    fallback_agent: Optional[Agent],
    prompt: str,
    graph: "KnowledgeGraph",
    stage: str,
):
    try:
        return primary_agent.run(prompt)
    except Exception as error:
        if not _is_rate_limit_error(error) or fallback_agent is None:
            raise

        graph.metadata["partial_results"] = True
        graph.metadata["rate_limit_hits"] = int(graph.metadata.get("rate_limit_hits", 0)) + 1
        graph.metadata.setdefault("fallbacks_used", []).append(stage)
        _append_graph_warning(
            graph,
            f"{stage} stage hit rate limits; fallback model was used.",
        )
        logger.warning(f"{stage} stage rate-limit'e takildi, fallback model kullaniliyor: {error}")
        return fallback_agent.run(prompt)


def _progress_path(seed_query: str) -> str:
    """Seed query'den progress dosya adını türet (safe karakterler)"""
    safe_name = "".join(c if c.isalnum() else "_" for c in seed_query)[:60]
    return f"output/progress_{safe_name}.json"


def _normalize_task_text(task: str) -> str:
    """Benzer görevleri tekilleştirmek için metni normalize et."""
    normalized = task.strip().lower()
    normalized = re.sub(r"https?://\S+", "", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _slugify(value: str) -> str:
    """Entity id üretmek için stabil slug."""
    slug = _normalize_task_text(value).replace(" ", "_")
    return slug[:80].strip("_")


def _parse_json_object(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """LLM çıktısından ilk JSON objesini güvenli çek."""
    try:
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(text[json_start:json_end])
    except json.JSONDecodeError as e:
        logger.warning(f"  ! JSON parse hatasi: {str(e)[:80]}")
    return fallback


def _extract_urls(text: str) -> List[str]:
    """Metindeki URL'leri bul."""
    return re.findall(r"https?://[^\s)>\"]+", text)


def _extract_domains(text: str) -> Set[str]:
    """Metindeki URL'lerden domain kümeyi çıkar."""
    domains: Set[str] = set()
    for url in _extract_urls(text):
        domain = urlparse(url).netloc.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            domains.add(domain)
    return domains


def _task_mentions_blocked_domain(task: str, blocked_domains: Set[str]) -> bool:
    """Task metni daha önce bloklanan bir domaini işaret ediyorsa yeniden deneme."""
    if not blocked_domains:
        return False
    normalized_task = task.lower()
    return any(domain in normalized_task for domain in blocked_domains)


def _result_indicates_domain_block(result_text: str) -> bool:
    """Crawl/araç sonucu bir erişim blokajına işaret ediyor mu?"""
    normalized = f" {result_text.lower()} "
    return any(pattern in normalized for pattern in BLOCK_INDICATOR_PATTERNS)


def _has_extraction_signal(
    result_text: str,
    seed_query: str,
    current_task: str,
    target_agent: str,
) -> bool:
    """Pahalı extraction çağrısından önce içerikte anlamlı sinyal var mı kontrol et."""
    compact_text = re.sub(r"\s+", " ", result_text).strip()
    if len(compact_text) < 200:
        return False

    normalized_text = f" {compact_text.lower()} "
    normalized_seed = _normalize_task_text(seed_query)
    normalized_task = _normalize_task_text(current_task)
    seed_terms = [term for term in normalized_seed.split() if len(term) > 2]

    mentions_seed = any(term in normalized_text for term in seed_terms)
    has_relation_cue = any(pattern in normalized_text for pattern in RELATION_SIGNAL_PATTERNS)
    has_profile_cue = target_agent == "github" and any(
        cue in normalized_text for cue in ["bio", "company", "repos", "followers", "organization"]
    )
    has_task_overlap = any(term in normalized_text for term in normalized_task.split() if len(term) > 3)

    return mentions_seed or has_relation_cue or has_profile_cue or has_task_overlap


def _source_type_from_url(url: str) -> str:
    """URL'den kaba kaynak tipi çıkar."""
    normalized = url.lower()
    if not normalized:
        return "unknown"
    if "github.com" in normalized:
        return "github"
    if "wikipedia.org" in normalized:
        return "wikipedia"
    if any(domain in normalized for domain in ["linkedin.com", "x.com", "twitter.com"]):
        return "profile"
    if any(
        domain in normalized
        for domain in [
            "sec.gov",
            ".gov/",
            ".gov.",
            ".edu/",
            ".edu.",
        ]
    ):
        return "official_record"
    if any(domain in normalized for domain in ["medium.com", "substack.com", "blog."]):
        return "blog"
    return "web"


def _source_tier_from_url(url: str, source_type: str) -> str:
    """Statik domain-tier sınıflandırması."""
    normalized = url.lower()
    if "sec.gov" in normalized:
        return "sec.gov"
    if "github.com" in normalized:
        return "github.com"
    if "linkedin.com" in normalized:
        return "linkedin.com"
    if "crunchbase.com" in normalized:
        return "crunchbase.com"
    if "medium.com" in normalized:
        return "medium.com"
    if "wikipedia.org" in normalized:
        return "wikipedia.org"
    if any(token in normalized for token in ["forum", "community", "discuss", "reddit.com"]):
        return "forum"
    if source_type == "official_record":
        return "official_site"
    if source_type == "blog":
        return "blog_generic"
    if source_type == "web":
        return "web_generic"
    return "unknown"


def _source_score(source_tier: str) -> float:
    """Kaynak tier'ına göre statik ağırlık."""
    return SOURCE_TIERS.get(source_tier, SOURCE_TIERS["unknown"])


def _normalize_confidence(value: Any) -> float:
    """Confidence değerini 0-1 aralığına çek."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(1.0, confidence))


def _short_evidence_snippet(text: str, limit: int = 240) -> str:
    """Evidence metnini tek satır ve kısa hale getir."""
    snippet = re.sub(r"\s+", " ", text).strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 3].rstrip() + "..."


def _infer_task_entity(task: str, seed_query: str, graph: "KnowledgeGraph") -> str:
    """Task'ın en çok hangi entity etrafında döndüğünü kaba olarak tahmin et."""
    normalized_task = _normalize_task_text(task)
    for node in sorted(graph.nodes, key=lambda item: len(item.get("name", "")), reverse=True):
        node_name = node.get("name", "")
        if node_name and _normalize_task_text(node_name) in normalized_task:
            return node_name
    return seed_query


def _resolve_relation_entity_id(
    graph: "KnowledgeGraph",
    entity_id: str,
    entity_name: str = "",
    entity_type: str = "entity",
) -> str:
    """Relation içindeki entity referansını graph içindeki canonical id'ye bağla."""
    explicit_id = entity_id.strip()
    if explicit_id:
        for node in graph.nodes:
            if node.get("id") == explicit_id:
                return explicit_id

    if entity_name and entity_type:
        existing_id = graph.find_entity_id(entity_type, entity_name)
        if existing_id:
            return existing_id

    if explicit_id:
        return explicit_id

    fallback_type = entity_type or "entity"
    return f"{fallback_type}_{_slugify(entity_name)}"


def _recalculate_relation_reviews(graph: "KnowledgeGraph") -> None:
    """Aynı triple birden fazla bağımsız kaynakla destekleniyorsa review bayrağını gevşet."""
    grouped_edges: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for edge in graph.edges:
        key = (edge.get("source", ""), edge.get("target", ""), edge.get("relation", ""))
        grouped_edges.setdefault(key, []).append(edge)

    for edges in grouped_edges.values():
        distinct_urls = {
            edge.get("source_url", "")
            for edge in edges
            if edge.get("source_url", "")
        }
        distinct_types = {
            edge.get("source_type", "")
            for edge in edges
            if edge.get("source_type", "")
        }
        corroborated_by = max(len(distinct_urls), 1)
        confidence_cap = 0.85 if corroborated_by >= 2 else 0.6
        has_strong_source = any(edge.get("source_tier_weight", 0.0) >= 0.7 for edge in edges)

        for edge in edges:
            edge["corroborated_by"] = corroborated_by
            llm_confidence = _normalize_confidence(edge.get("llm_confidence", edge.get("confidence", 0.0)))
            confidence = min(llm_confidence, confidence_cap)
            source_tier_weight = float(edge.get("source_tier_weight", SOURCE_TIERS["unknown"]))
            edge["confidence"] = confidence
            edge["final_score"] = round(confidence * source_tier_weight, 4)
            if corroborated_by >= 2 and (len(distinct_types) >= 2 or has_strong_source) and edge["final_score"] >= 0.5:
                edge["needs_review"] = False
            else:
                edge["needs_review"] = True


def _is_low_signal_task(task: str, seed_query: str) -> bool:
    """Ana hedefe katkısı düşük görevleri erken ele."""
    normalized = _normalize_task_text(task)
    seed_normalized = _normalize_task_text(seed_query)

    if not normalized:
        return True

    if any(pattern in normalized for pattern in OFF_SCOPE_PATTERNS):
        return True

    if any(pattern in normalized for pattern in LOW_SIGNAL_PATTERNS):
        if seed_normalized not in normalized:
            return True

    return False


def _compute_task_priority(task: str, target_agent: str, depth: int, seed_query: str) -> int:
    """Daha ilgili ve daha sığ görevleri önce çalıştır."""
    normalized = _normalize_task_text(task)
    seed_terms = [term for term in _normalize_task_text(seed_query).split() if len(term) > 2]

    score = 100 - (depth * 15)

    if target_agent == "github":
        score += 12
    elif target_agent == "wikipedia":
        score += 8

    if any(term in normalized for term in seed_terms):
        score += 20

    if _is_low_signal_task(task, seed_query):
        score -= 40

    return score


def _enqueue_task(
    task_queue: list,
    task: str,
    target_agent: str,
    depth: int,
    seed_query: str,
    queued_keys: Set[Tuple[str, str]],
) -> bool:
    """Öncelik puanıyla kuyruğa görev ekle."""
    normalized_task = _normalize_task_text(task)
    if not normalized_task:
        return False

    queue_key = (normalized_task, target_agent)
    if queue_key in queued_keys:
        return False

    priority = _compute_task_priority(task, target_agent, depth, seed_query)
    heapq.heappush(
        task_queue,
        (
            -priority,
            depth,
            next(TASK_QUEUE_SEQUENCE),
            {"task": task.strip(), "target_agent": target_agent, "depth": depth},
        ),
    )
    queued_keys.add(queue_key)
    return True


def _dequeue_task(task_queue: list, queued_keys: Set[Tuple[str, str]]) -> Optional[Dict[str, Any]]:
    """Öncelikli kuyruktan sıradaki görevi al."""
    if not task_queue:
        return None

    _, _, _, task = heapq.heappop(task_queue)
    queued_keys.discard((_normalize_task_text(task["task"]), task["target_agent"]))
    return task


def _graph_contains_task(graph: "KnowledgeGraph", task: str) -> bool:
    """Grafikte zaten task-type olarak işlenmiş eş görev var mı kontrol et."""
    normalized_task = _normalize_task_text(task)
    return any(
        node.get("type") == "task" and _normalize_task_text(node.get("name", "")) == normalized_task
        for node in graph.nodes
    )


def _merge_extracted_graph(
    graph: "KnowledgeGraph",
    extraction: Dict[str, Any],
    fallback_source_url: str = "",
) -> Tuple[int, int]:
    """Entity ve relation çıktısını knowledge graph'a işle."""
    entities = extraction.get("entities", [])
    relations = extraction.get("relations", [])
    added_relations = 0
    added_entities = 0
    entity_id_map: Dict[str, str] = {}

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_name = str(entity.get("name", "")).strip()
        entity_type = str(entity.get("type", "entity")).strip().lower()
        if not entity_name:
            continue

        entity_id = str(entity.get("id", "")).strip()
        if not entity_id:
            entity_id = f"{entity_type}_{_slugify(entity_name)}"

        before_id = graph.find_entity_id(entity_type, entity_name)
        canonical_id = graph.add_node(
            entity_id,
            entity_type,
            entity_name,
            str(entity.get("source_url", "")).strip() or fallback_source_url,
        )
        if before_id is None:
            added_entities += 1
        entity_id_map[entity_id] = canonical_id

    existing_edges = {
        (
            edge.get("source", ""),
            edge.get("target", ""),
            edge.get("relation", ""),
            edge.get("source_url", ""),
        )
        for edge in graph.edges
    }
    retrieved_at = datetime.now(timezone.utc).isoformat()

    for relation in relations:
        if not isinstance(relation, dict):
            continue

        source = str(relation.get("source", "")).strip()
        target = str(relation.get("target", "")).strip()
        rel_type = str(relation.get("relation", "")).strip().upper()
        if not source or not target or not rel_type:
            continue

        source_name = str(relation.get("source_name", "")).strip()
        target_name = str(relation.get("target_name", "")).strip()
        source_type_hint = str(relation.get("source_type_hint", "")).strip().lower()
        target_type_hint = str(relation.get("target_type_hint", "")).strip().lower()

        source = entity_id_map.get(
            source,
            _resolve_relation_entity_id(graph, source, source_name, source_type_hint),
        )
        target = entity_id_map.get(
            target,
            _resolve_relation_entity_id(graph, target, target_name, target_type_hint),
        )

        edge_source_url = str(relation.get("source_url", "")).strip() or fallback_source_url
        edge_key = (source, target, rel_type, edge_source_url)
        if edge_key in existing_edges:
            continue

        llm_confidence = _normalize_confidence(relation.get("confidence", 0.0))
        source_type = _source_type_from_url(edge_source_url)
        source_tier = _source_tier_from_url(edge_source_url, source_type)
        source_tier_weight = _source_score(source_tier)
        evidence_span = _short_evidence_snippet(str(relation.get("evidence_span", relation.get("evidence_snippet", "")).strip()))

        if not evidence_span:
            evidence_span = "LLM extraction produced relation without direct quoted evidence."

        confidence = min(llm_confidence, 0.6)
        final_score = round(confidence * source_tier_weight, 4)
        needs_review = True

        graph.add_edge(
            source,
            target,
            rel_type,
            confidence,
            edge_source_url,
            source_type=source_type,
            source_tier=source_tier,
            source_tier_weight=source_tier_weight,
            evidence_snippet=evidence_span,
            evidence_span=evidence_span,
            needs_review=needs_review,
            retrieved_at=retrieved_at,
            corroborated_by=1,
            llm_confidence=llm_confidence,
            final_score=final_score,
        )
        existing_edges.add(edge_key)
        added_relations += 1

    _recalculate_relation_reviews(graph)
    return added_entities, added_relations


def _extract_graph_facts(
    seed_query: str,
    current_task: str,
    result_text: str,
    graph: "KnowledgeGraph",
) -> Dict[str, Any]:
    """Araştırma çıktısından entity ve relation çıkar."""
    urls = _extract_urls(result_text)
    source_hints = [
        {
            "url": url,
            "source_type": _source_type_from_url(url),
            "source_tier": _source_tier_from_url(url, _source_type_from_url(url)),
            "source_score": _source_score(_source_tier_from_url(url, _source_type_from_url(url))),
        }
        for url in urls[:10]
    ]
    extraction_prompt = "\n".join(
        [
            f"Ana hedef: {seed_query}",
            f"Gorev: {current_task}",
            "Cikti:",
            result_text[:3200],
            f"Tespit edilen URL'ler: {json.dumps(urls[:10], ensure_ascii=False)}",
            f"Kaynak ipuclari: {json.dumps(source_hints, ensure_ascii=False)}",
        ]
    )
    extraction_result = _run_agent_with_fallback(
        extraction_agent,
        fallback_extraction_agent,
        extraction_prompt,
        graph,
        "extraction",
    )
    extraction_text = (
        extraction_result.content if hasattr(extraction_result, "content") else str(extraction_result)
    )
    return _parse_json_object(extraction_text, {"entities": [], "relations": []})


def _marginal_gain_is_low(result_urls: List[str], seen_source_urls: Set[str]) -> bool:
    """Yeni bulunan URL'ler büyük ölçüde önceden görüldüyse düşük marjinal kazanç say."""
    unique_urls = {url for url in result_urls if url}
    if not unique_urls:
        return False
    overlap_count = len(unique_urls & seen_source_urls)
    overlap_ratio = overlap_count / len(unique_urls)
    return overlap_ratio >= MARGINAL_GAIN_OVERLAP_THRESHOLD


def _filter_new_tasks(
    new_tasks: List[Dict[str, Any]],
    seed_query: str,
    graph: "KnowledgeGraph",
    seen_tasks: Set[Tuple[str, str]],
    queued_keys: Set[Tuple[str, str]],
    next_depth: int,
) -> List[Dict[str, Any]]:
    """LLM'in ürettiği görevleri relevance ve duplicate kontrollerinden geçir."""
    filtered: List[Dict[str, Any]] = []

    for new_task in new_tasks:
        if not isinstance(new_task, dict):
            continue

        task_text = str(new_task.get("task", "")).strip()
        target_agent = str(new_task.get("target_agent", "web")).strip() or "web"
        normalized_key = (_normalize_task_text(task_text), target_agent)

        if _is_low_signal_task(task_text, seed_query):
            logger.info(f"  - Alakasiz/low-signal görev elendi: {task_text[:80]}")
            continue
        if normalized_key in seen_tasks or normalized_key in queued_keys:
            logger.info(f"  - Yinelenen görev elendi: {task_text[:80]}")
            continue
        if _graph_contains_task(graph, task_text):
            logger.info(f"  - Grafikte zaten bulunan görev elendi: {task_text[:80]}")
            continue

        filtered.append(
            {
                "task": task_text,
                "target_agent": target_agent if target_agent in AGENT_MAP else "web",
                "depth": next_depth,
                "reason": str(new_task.get("reason", "")),
            }
        )

    filtered.sort(
        key=lambda item: _compute_task_priority(
            item["task"], item["target_agent"], item["depth"], seed_query
        ),
        reverse=True,
    )
    return filtered[:MAX_NEW_TASKS_PER_STEP]


def _save_checkpoint(
    path: str,
    graph: "KnowledgeGraph",
    task_queue: list,
    seen_tasks: set,
    queued_keys: Set[Tuple[str, str]],
    entity_task_counts: Dict[str, int],
    seen_source_urls: Set[str],
    blocked_domains: Set[str],
):
    """Atomik yazma: temp dosya + os.replace (kesinti sırasında bozulma engellemek için)"""
    state = {
        "graph": {"nodes": graph.nodes, "edges": graph.edges, "metadata": graph.metadata},
        "task_queue": [item[3] for item in sorted(task_queue, key=lambda item: (item[0], item[1], item[2], item[3]["task"]))],
        "seen_tasks": list(seen_tasks),
        "queued_keys": list(queued_keys),
        "entity_task_counts": entity_task_counts,
        "seen_source_urls": sorted(seen_source_urls),
        "blocked_domains": sorted(blocked_domains),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    logger.info(f"✓ Checkpoint kaydedildi: {path}")


def _load_checkpoint(path: str, seed_query: str):
    """Checkpoint'ten durumu yükle"""
    if not os.path.exists(path):
        return None
    
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        graph = KnowledgeGraph(
            nodes=state["graph"]["nodes"],
            edges=state["graph"]["edges"],
            metadata=state["graph"].get("metadata", {}),
        )
        # Seen_tasks'i set olarak döndür (tuple'lardan)
        seen_tasks = set(tuple(t) for t in state["seen_tasks"])
        queued_keys = set(tuple(t) for t in state.get("queued_keys", []))
        entity_task_counts = {
            str(key): int(value)
            for key, value in state.get("entity_task_counts", {}).items()
        }
        seen_source_urls = set(state.get("seen_source_urls", []))
        blocked_domains = set(state.get("blocked_domains", []))
        task_queue = []
        for task in state["task_queue"]:
            _enqueue_task(
                task_queue,
                task=task["task"],
                target_agent=task["target_agent"],
                depth=task["depth"],
                seed_query=seed_query,
                queued_keys=queued_keys,
            )
        return graph, task_queue, seen_tasks, queued_keys, entity_task_counts, seen_source_urls, blocked_domains
    except Exception as e:
        logger.error(f"Checkpoint yüklenirken hata: {e}")
        return None


def run_research(
    seed_query: str,
    max_depth: int = MAX_DEPTH,
    resume: bool = False,
    max_tasks: int = DEFAULT_MAX_TASKS,
    max_tasks_per_entity: int = DEFAULT_MAX_TASKS_PER_ENTITY,
) -> KnowledgeGraph:
    """Araştırma görev kuyruğunu çalıştır - checkpoint desteğiyle"""
    
    checkpoint_path = _progress_path(seed_query)
    
    # Checkpoint yüklemeye çalış
    loaded = _load_checkpoint(checkpoint_path, seed_query) if resume else None
    
    if loaded:
        graph, task_queue, seen_tasks, queued_keys, entity_task_counts, seen_source_urls, blocked_domains = loaded
        logger.info(f"📂 Checkpoint'ten devam ediliyor: {len(task_queue)} görev kaldı")
    else:
        graph = KnowledgeGraph()
        task_queue = []
        seen_tasks = set()
        queued_keys = set()
        entity_task_counts = {}
        seen_source_urls = set()
        blocked_domains = set()
        _enqueue_task(task_queue, seed_query, "web", 0, seed_query, queued_keys)
        logger.info(f"🚀 Yeni araştırma başlatılıyor: {seed_query}")
    
    processed_count = 0
    
    try:
        while task_queue:
            if processed_count >= max_tasks:
                logger.warning(f"Task budget sinirina ulasildi: {processed_count}/{max_tasks}")
                break

            current = _dequeue_task(task_queue, queued_keys)
            if current is None:
                break
            
            # Derinlik kontrolü
            if current["depth"] >= max_depth:
                logger.debug(f"⚫ Max derinliğe ulaşıldı: {current['task'][:50]}")
                continue
            
            # Tekrarlama kontrolü
            key = (_normalize_task_text(current["task"]), current["target_agent"])
            if key in seen_tasks:
                logger.debug(f"⏭️  Zaten işlendi: {current['task'][:50]}")
                continue

            if _task_mentions_blocked_domain(current["task"], blocked_domains):
                logger.info(f"  - Bloklu domain nedeniyle görev atlandı: {current['task'][:80]}")
                continue

            task_entity = _infer_task_entity(current["task"], seed_query, graph)
            normalized_entity = _normalize_task_text(task_entity)
            if entity_task_counts.get(normalized_entity, 0) >= max_tasks_per_entity:
                logger.info(f"  - Entity task limiti nedeniyle atlandi: {task_entity[:60]}")
                continue

            seen_tasks.add(key)
            entity_task_counts[normalized_entity] = entity_task_counts.get(normalized_entity, 0) + 1
            
            logger.info(f"▶️  [depth={current['depth']}] {current['target_agent']}: {current['task'][:60]}")
            
            try:
                # Agent'ı seç ve çalıştır
                agent = AGENT_MAP.get(current["target_agent"], discovery_agent)
                result = agent.run(current["task"])
                result_text = result.content if hasattr(result, "content") else str(result)
                result_urls = _extract_urls(result_text)
                result_domains = _extract_domains(result_text)
                low_marginal_gain = _marginal_gain_is_low(result_urls, seen_source_urls)
                seen_source_urls.update(result_urls)

                if _result_indicates_domain_block(result_text):
                    newly_blocked = result_domains - blocked_domains
                    blocked_domains.update(result_domains)
                    if newly_blocked:
                        logger.warning(
                            f"  ! Domain bloklandi, oturum boyunca atlanacak: {', '.join(sorted(newly_blocked))}"
                        )

                has_extraction_signal = _has_extraction_signal(
                    result_text,
                    seed_query=seed_query,
                    current_task=current["task"],
                    target_agent=current["target_agent"],
                )
                if has_extraction_signal:
                    extraction = _extract_graph_facts(seed_query, current["task"], result_text, graph)
                else:
                    logger.info("  - Düşük sinyalli içerik: extraction çağrısı atlandı")
                    extraction = {"entities": [], "relations": []}

                added_entity_count, merged_relation_count = _merge_extracted_graph(
                    graph,
                    extraction,
                    fallback_source_url=result_urls[0] if result_urls else "",
                )
                if merged_relation_count > 0:
                    logger.info(f"  → {merged_relation_count} iliski graph'a eklendi")
                elif added_entity_count > 0:
                    logger.info(f"  → {added_entity_count} entity graph'a eklendi")
                else:
                    logger.info("  - Graph icin anlamli entity/iliski cikmadi")
                
                # Reasoning agent'a sor: yeni görevler?
                logger.debug(f"  → Reasoning agent çalışıyor...")
                reasoning_result = _run_agent_with_fallback(
                    reasoning_agent,
                    fallback_reasoning_agent,
                    f"Bulunan bilgi: {result_text[:500]}\nOrijinal görev: {current['task']}",
                    graph,
                    "reasoning",
                )
                
                reasoning_text = reasoning_result.content if hasattr(reasoning_result, "content") else str(reasoning_result)
                
                reasoning_json = _parse_json_object(
                    reasoning_text,
                    {"new_tasks": [], "confidence": 0.0},
                )

                if low_marginal_gain and merged_relation_count == 0 and added_entity_count == 0:
                    logger.info("  - Marginal gain düşük, yeni görev türetme atlandi")
                    reasoning_json = {"new_tasks": [], "confidence": 0.0}
                
                filtered_tasks = _filter_new_tasks(
                    reasoning_json.get("new_tasks", []),
                    seed_query=seed_query,
                    graph=graph,
                    seen_tasks=seen_tasks,
                    queued_keys=queued_keys,
                    next_depth=current["depth"] + 1,
                )
                new_count = len(filtered_tasks)
                if new_count > 0:
                    logger.info(f"  → {new_count} yeni görev türetildi")
                
                for new_task in filtered_tasks:
                    _enqueue_task(
                        task_queue,
                        task=new_task["task"],
                        target_agent=new_task["target_agent"],
                        depth=new_task["depth"],
                        seed_query=seed_query,
                        queued_keys=queued_keys,
                    )
                
                processed_count += 1
                graph.metadata["processed_tasks"] = processed_count
                
                # Checkpoint her 5 görevde bir
                if processed_count % 5 == 0:
                    _save_checkpoint(
                        checkpoint_path,
                        graph,
                        task_queue,
                        seen_tasks,
                        queued_keys,
                        entity_task_counts,
                        seen_source_urls,
                        blocked_domains,
                    )
                
            except Exception as e:
                if _is_rate_limit_error(e):
                    graph.metadata["partial_results"] = True
                    graph.metadata["rate_limit_hits"] = int(graph.metadata.get("rate_limit_hits", 0)) + 1
                    _append_graph_warning(
                        graph,
                        "One or more model calls hit rate limits; partial results may be returned.",
                    )
                logger.error(f"  ! Görev işleminde hata: {str(e)[:100]}")
                continue
    
    except KeyboardInterrupt:
        logger.warning("\n⏸️  Ctrl+C alındı, checkpoint kaydedilip çıkılıyor...")
        _save_checkpoint(
            checkpoint_path,
            graph,
            task_queue,
            seen_tasks,
            queued_keys,
            entity_task_counts,
            seen_source_urls,
            blocked_domains,
        )
        raise
    
    # Başarıyla tamamlandı - checkpoint dosyasını sil
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
        logger.info(f"🧹 Checkpoint dosyası silindi")
    
    if graph.metadata.get("rate_limit_hits", 0) > 0 and (graph.nodes or graph.edges):
        graph.metadata["partial_results"] = True
    logger.info(f"✅ Araştırma tamamlandı: {len(graph.nodes)} düğüm, {len(graph.edges)} kenar")
    
    return graph


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OSINT Araştırma Ajanı - Kişi/Kurum profili oluştur"
    )
    parser.add_argument(
        "seed_query", 
        nargs="?", 
        default="Esma Cerit",
        help="Araştırmaya başlanacak kişi/kurum adı"
    )
    parser.add_argument(
        "--resume", 
        action="store_true", 
        help="Önceki checkpoint'ten devam et"
    )
    parser.add_argument(
        "--max-depth", 
        type=int, 
        default=MAX_DEPTH,
        help=f"Maksimum araştırma derinliği (default: {MAX_DEPTH})"
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=DEFAULT_MAX_TASKS,
        help=f"İşlenecek maksimum görev sayısı (default: {DEFAULT_MAX_TASKS})"
    )
    parser.add_argument(
        "--max-tasks-per-entity",
        type=int,
        default=DEFAULT_MAX_TASKS_PER_ENTITY,
        help=f"Aynı entity için işlenecek maksimum görev sayısı (default: {DEFAULT_MAX_TASKS_PER_ENTITY})"
    )
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("OSINT ARAŞTIRMA AJANI")
    logger.info("=" * 70)
    
    try:
        kg = run_research(
            args.seed_query,
            max_depth=args.max_depth,
            resume=args.resume,
            max_tasks=args.max_tasks,
            max_tasks_per_entity=args.max_tasks_per_entity,
        )
        
        # Sonucu dosyaya yaz
        output_path = "output/knowledge_graph.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(kg.to_json())
        
        logger.info(f"📊 Sonuç kaydedildi: {output_path}")
        logger.info(f"   - {len(kg.nodes)} düğüm")
        logger.info(f"   - {len(kg.edges)} kenar")
        
    except KeyboardInterrupt:
        logger.info("\n👋 Çıkılıyor...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Hata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
