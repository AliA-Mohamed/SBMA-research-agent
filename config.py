"""Configuration for the SBMA Research Agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "database/sbma_research.db")
LOG_FILE = BASE_DIR / os.getenv("LOG_FILE", "logs/sbma_agent.log")
OUTPUTS_DIR = BASE_DIR / "outputs"
TEXTBOOK_DIR = OUTPUTS_DIR / "textbook"
WEEKLY_REPORTS_DIR = OUTPUTS_DIR / "weekly_reports"
ANALYTICS_DIR = OUTPUTS_DIR / "analytics"
RAW_XML_DIR = BASE_DIR / "data" / "raw_xml"
CHECKPOINTS_DIR = BASE_DIR / "data" / "checkpoints"

# Ensure directories exist
for d in [TEXTBOOK_DIR, WEEKLY_REPORTS_DIR, ANALYTICS_DIR, RAW_XML_DIR, CHECKPOINTS_DIR,
          LOG_FILE.parent]:
    d.mkdir(parents=True, exist_ok=True)

# --- API Keys ---
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

# --- PubMed Search ---
PUBMED_SEARCH_QUERY = (
    '"spinal and bulbar muscular atrophy"[Title/Abstract] OR '
    '"Kennedy disease"[Title/Abstract] OR '
    '"Kennedy\'s disease"[Title/Abstract] OR '
    '"SBMA"[Title/Abstract] OR '
    '"X-linked spinal and bulbar muscular atrophy"[Title/Abstract] OR '
    '"bulbospinal muscular atrophy"[Title/Abstract] OR '
    '("androgen receptor"[Title/Abstract] AND "CAG repeat"[Title/Abstract] '
    'AND ("motor neuron"[Title/Abstract] OR "muscular atrophy"[Title/Abstract]))'
)

# --- SBMA Relevance Filter ---
# Terms that CONFIRM an article is about SBMA (case-insensitive match in title/abstract)
SBMA_POSITIVE_TERMS = [
    "spinal and bulbar muscular atrophy",
    "spinal bulbar muscular atrophy",
    "bulbar and spinal muscular atrophy",
    "kennedy disease",
    "kennedy's disease",
    "kennedys disease",
    "kennedy syndrome",
    "spinobulbar muscular atrophy",
    "spinal and bulbar muscle atrophy",
    "bulbospinal muscular atrophy",
    "bulbospinal neuronopathy",
    "x-linked spinal and bulbar muscular atrophy",
    "x-linked bulbar and spinal muscular atrophy",
    "x-linked bulbospinal",
    "x-linked recessive bulbospinal",
    "kennedy-alter-sung",
    "kas syndrome",
    "sbma",
]

# If an article matches ONLY via the generic "androgen receptor + CAG repeat" clause,
# it must also contain at least one of these confirming terms:
SBMA_AR_CAG_CONFIRMING_TERMS = [
    "spinal and bulbar muscular atrophy",
    "kennedy disease",
    "kennedy's disease",
    "sbma",
    "bulbospinal",
    "motor neuron degeneration",
    "lower motor neuron",
]

# Articles primarily about these diseases (not SBMA) should be EXCLUDED
# even if they mention SBMA in passing. An article is excluded if its title
# contains one of these terms AND does NOT contain any SBMA_POSITIVE_TERMS in the title.
SBMA_EXCLUDE_PRIMARY_DISEASES = [
    "spinal muscular atrophy type",  # SMA types I-IV
    "amyotrophic lateral sclerosis",
    "huntington",
    "spinocerebellar ataxia",
    "machado-joseph",
    "dentatorubral",
    "drpla",
    "friedreich",
    "myotonic dystrophy",
    "duchenne",
    "becker muscular dystrophy",
    "facioscapulohumeral",
    "limb-girdle",
    "charcot-marie-tooth",
    "prostate cancer",
    "prostate neoplasm",
    "breast cancer",
    "androgen insensitivity syndrome",
]

# Terms indicating a non-disease use of "SBMA" (material science, chemistry, microbiology)
# Used by the keyword-based filter as a quick pre-screen; the LLM-based filter
# (run_llm_relevance_filter.py) is more accurate for final classification.
SBMA_FALSE_POSITIVE_TERMS = [
    "sulfobetaine",
    "methacrylate",
    "zwitterionic",
    "polymer",
    "electrolyte",
    "hydrogel",
    "membrane",
    "antifouling",
    "biocompatible",
    "copolymer",
    "antimicrobial peptide",
    "sbma transporter",
    "bacasm",
    "benzylmercapturic",
    "toluene",
    "benzene metabolite",
    "urinary metabolite",
    "wound dressing",
    "contact lens",
    "nanoparticle",
    "coating",
    "antibacterial",
    "biofilm",
    "grafting",
    "biomaterial",
    "echocardiography",
    "myocardial",
    "ventricular septal",
]

# Rate limits (requests per second)
NCBI_RATE_LIMIT = 3 if NCBI_API_KEY else 1  # 3/sec with key, 1/sec without
CROSSREF_RATE_LIMIT = 50  # polite pool
SEMANTIC_SCHOLAR_RATE_LIMIT = 10  # 100/5min ~ 10 safe
UNPAYWALL_RATE_LIMIT = 10

# --- LLM Backend ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")  # "ollama", "gemini", or "claude"

# --- Ollama ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_EXTRACTION_MODEL = os.getenv("OLLAMA_EXTRACTION_MODEL", OLLAMA_MODEL)
OLLAMA_SYNTHESIS_MODEL = os.getenv("OLLAMA_SYNTHESIS_MODEL", OLLAMA_MODEL)

# --- Gemini API ---
GEMINI_EXTRACTION_MODEL = "gemini-2.5-flash-lite"  # bulk extraction (1,000 req/day free tier)
GEMINI_SYNTHESIS_MODEL = "gemini-2.5-flash-lite"              # chapter synthesis (same model to maximize free quota)
GEMINI_MAX_TOKENS = 4096

# --- Claude API ---
CLAUDE_EXTRACTION_MODEL = os.getenv("CLAUDE_EXTRACTION_MODEL", "claude-sonnet-4-6")
CLAUDE_SYNTHESIS_MODEL = os.getenv("CLAUDE_SYNTHESIS_MODEL", "claude-opus-4-6")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

# --- Ingestion ---
INGESTION_BATCH_SIZE = 100  # articles per batch for PubMed fetch
CHECKPOINT_INTERVAL = 50    # save progress every N articles
RETRY_MAX_ATTEMPTS = 5
RETRY_WAIT_MIN = 1  # seconds
RETRY_WAIT_MAX = 60  # seconds

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
