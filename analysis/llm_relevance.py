"""LLM-based SBMA relevance classifier.

Determines whether a scientific article is relevant to Spinal and Bulbar
Muscular Atrophy (Kennedy's disease) research by sending the title and
abstract to the configured LLM backend.
"""

import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger

logger = setup_logger("llm_relevance")

CLASSIFICATION_PROMPT = """You are a biomedical research librarian specializing in neuromuscular diseases.

Your task: determine if the following scientific article is **relevant** to research on **Spinal and Bulbar Muscular Atrophy (SBMA)**, also known as **Kennedy's disease**.

SBMA is an X-linked neurodegenerative disease caused by a CAG trinucleotide repeat expansion in the androgen receptor (AR) gene. It affects lower motor neurons and causes progressive muscle weakness, bulbar dysfunction, and androgen insensitivity features.

An article IS relevant if it covers ANY of the following:
- SBMA / Kennedy's disease directly (clinical, genetic, molecular, therapeutic)
- Androgen receptor biology related to polyglutamine expansion or motor neuron disease
- CAG repeat expansion mechanisms relevant to SBMA pathology
- Polyglutamine disease mechanisms (protein aggregation, toxicity, chaperones, degradation pathways) that apply to SBMA
- Motor neuron degeneration, especially lower motor neuron diseases
- Neuromuscular disease genetics, diagnosis, or treatment where SBMA is discussed
- Animal or cell models of SBMA or polyglutamine-expanded AR
- Therapeutic approaches for polyglutamine diseases (gene silencing, ASOs, small molecules, etc.)
- Reviews of trinucleotide repeat / polyglutamine diseases that include SBMA as a key topic

An article is NOT relevant if:
- "SBMA" refers to sulfobetaine methacrylate (a polymer/material science term)
- It's about polymers, coatings, hydrogels, antifouling surfaces, zwitterionic materials
- It's about plasmid biology (TraM, oriT, conjugation)
- It's about cardiology (echocardiography, ventricular strain)
- It's about volatile organic compounds or toxicology biomarkers
- It's about a completely different disease (e.g., only ALS, only SMA, only Huntington's) with no meaningful connection to SBMA
- SBMA is only mentioned in a list with no substantive discussion

---

Title: {title}

Abstract: {abstract}

---

Respond with ONLY a JSON object (no markdown, no explanation):
{{"relevant": true/false, "reason": "one short sentence explaining why"}}"""


def classify_article_relevance(title: str, abstract: str) -> dict:
    """Classify whether an article is relevant to SBMA research using the LLM.

    Args:
        title: Article title.
        abstract: Article abstract text.

    Returns:
        dict with keys "relevant" (bool) and "reason" (str).
        On error, defaults to relevant=True (keep by default).
    """
    prompt = CLASSIFICATION_PROMPT.format(
        title=title or "(no title)",
        abstract=abstract or "(no abstract available)",
    )

    backend = config.LLM_BACKEND
    max_retries = 5

    for attempt in range(max_retries):
        try:
            if backend == "gemini":
                from google import genai
                client = genai.Client(api_key=config.GEMINI_API_KEY)
                response = client.models.generate_content(
                    model=config.GEMINI_EXTRACTION_MODEL,
                    contents=prompt,
                    config={"max_output_tokens": 150, "response_mime_type": "application/json"},
                )
                raw = response.text
            elif backend == "ollama":
                import requests
                resp = requests.post(
                    f"{config.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": config.OLLAMA_MODEL,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {"num_predict": 150},
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                raw = resp.json()["response"]
            elif backend == "claude":
                import anthropic
                client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                message = client.messages.create(
                    model=config.CLAUDE_EXTRACTION_MODEL,
                    max_tokens=150,
                    temperature=0,
                    system="Respond with valid JSON only, no markdown.",
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = message.content[0].text
            else:
                raise ValueError(f"Unknown LLM_BACKEND: {backend}")

            # Extract JSON (Gemini sometimes adds trailing text)
            raw = raw.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                raw = raw[start:end]
            result = json.loads(raw)
            return {
                "relevant": bool(result.get("relevant", True)),
                "reason": result.get("reason", ""),
            }

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response (attempt {attempt+1}): {raw[:200]}")
            if attempt == max_retries - 1:
                return {"relevant": True, "reason": f"PARSE ERROR — kept by default: {e}"}
        except Exception as e:
            wait = min(2 ** attempt * 2, 60)
            logger.warning(f"LLM error (attempt {attempt+1}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
            if attempt == max_retries - 1:
                return {"relevant": True, "reason": f"LLM ERROR — kept by default: {e}"}

    return {"relevant": True, "reason": "fallback — kept by default"}
