"""Generate monthly SBMA newsletter using the configured LLM backend."""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.ollama_client import call_llm

logger = setup_logger("newsletter_generator")

NEWSLETTER_SYSTEM_PROMPT = """\
You are the scientific editor of the SBMA Research Monthly Newsletter. Your readers \
include neurologists, genetic counselors, molecular biologists, patients, and caregivers \
with an interest in Spinal and Bulbar Muscular Atrophy (Kennedy disease).

Writing standards:
- Write in the register of a Nature Medicine News & Views piece: factual, measured, precise.
- Anchor every claim to a specific trial, finding, PMID, or NCT ID. Remove any sentence \
  that cannot be tied to concrete data.
- Cite sources inline using [Author et al., Year] format and list full references at the end.
- Use active voice. Keep sentences under 30 words where possible.
- When a section has no data (e.g., zero new publications), state the fact in one sentence \
  and move on. Do not pad with motivational commentary or filler.

Strictly avoid these phrases and constructions:
- "it's important to note", "it is worth mentioning", "exciting progress"
- "this underscores", "the field continues to", "a robust landscape"
- "substantial promise", "comprehensive", "multifaceted approach"
- "driving force", "the bedrock of", "the cornerstone of"
- "continues to offer", "remains a beacon", "journey toward"
- "cutting-edge", "groundbreaking", "game-changing"
- "In this edition", "Welcome to the [Month] edition"
- "As we navigate", "it's important to remember"
- Sentences beginning with "This month" more than once per section
- Rhetorical questions used as filler

Tone: authoritative, concise, scientifically rigorous. Not promotional.\
"""

NEWSLETTER_PROMPT_TEMPLATE = """\
Today's date: {today}
Newsletter period: {period_label} ({start_date} to {end_date})

Write the complete SBMA Monthly Newsletter for {period_label} using the data below.

---
## NEW RESEARCH THIS MONTH ({article_count} new articles)

{articles_section}

---
## CLINICAL TRIALS UPDATE

{trials_section}

---
## RECENT CONFERENCE HIGHLIGHTS

{recent_conferences_section}

---
## CONFERENCES & SCIENTIFIC EVENTS (Future)

{conferences_section}

---
## EXISTING KNOWLEDGE BASE CONTEXT (brief chapter summaries for reference)

{knowledge_context}

---

Output the newsletter in Markdown using EXACTLY this structure. \
Omit any section entirely if it has no substantive content — do not insert placeholder \
text, empty tables, or filler paragraphs.

# SBMA Research Monthly Newsletter — {period_label}

> *Published {today} · {article_count} new articles this month*

---

## Editor's Overview

[If there are new publications: write 2-3 focused paragraphs on the month's key findings. \
Lead with the single most significant result. Mention specific papers by first author and \
journal. Close with what these findings mean for the field's trajectory.

If there are zero new publications: state that no new articles were indexed during the \
reporting period, note the number of active trials, and close. Maximum 3 sentences. \
Do not add motivational filler.]

---

## Research Highlights

[ONLY include this section if article_count > 0. \
Group articles by category: High-Impact Findings, Clinical & Translational, \
Basic Science & Mechanisms, Reviews & Meta-analyses. For each article:

### [Category Name]

**[Article Title]**
*First Author et al.* (Journal, Year) — PMID: XXXXX · DOI: XX.XXXX/XXXX

[2-4 sentence summary: state the question, the method, and the result. \
Note clinical or mechanistic significance in the final sentence.]

If there are no articles, OMIT this entire section. Do not write "No new articles".]

---

## Clinical Pipeline

[Write a factual summary of active trials. For each trial, state: name, NCT ID, phase, \
intervention, enrollment status, and sponsor. Use one short paragraph per trial or group \
closely related trials. End with the summary table below. \
Direct readers to clinicaltrials.gov for eligibility details.]

| Trial | Phase | Intervention | Status | NCT ID |
|-------|-------|-------------|--------|--------|
{full_trials_table}

---

## Recent Conference Highlights

[ONLY include this section if there are recent conferences provided in the data.
Write a 2-3 paragraph professional overview of the recent events listed. Check the "NEW RESEARCH THIS MONTH" section above to cross-reference any recently published PubMed articles that appear to be from or related to this conference. If there are related articles, highlight them here. If not, ignore specific findings and simply provide a generalized scientific overview of the conference's significance to motor neuron diseases. Do NOT fabricate specific abstract results.]

---

## Conferences & Scientific Events

[List each FUTURE conference with its FULL URL as a markdown hyperlink. Format:

* **[Conference Name](URL)** — Organizer. One-sentence description of SBMA relevance.

Do NOT write "check website for dates". If dates are unknown, omit dates silently. \
Always include the URL as a clickable markdown link.]

---

## Open Questions in the Field

[List 4-6 specific, testable scientific questions raised by this month's data (new articles \
or trial landscape). Each question should be precise enough that a graduate student could \
design a study around it. If no new articles, base questions on the trial portfolio and \
known gaps in SBMA biology.

Do not use generic questions like "how can we better understand X" — be specific about \
the molecule, pathway, or clinical endpoint.]

---

## Full Publication List

[ONLY include this section if article_count > 0.]

| # | Title | First Author | Journal | Year | PMID | DOI |
|---|-------|-------------|---------|------|------|-----|
{full_publication_table}

[If no articles, OMIT this entire section.]

---

## References

[ONLY include this section if there are cited references. \
Number all references cited in the newsletter body:
[N] Last FM, Last FM, et al. "Title." *Journal* Year;Vol(Issue):Pages. PMID: XXXXXXXX. DOI: XX.XXXX/XXXX

If no references, OMIT this entire section.]

---

*This newsletter is generated by the SBMA Research Agent and reviewed by the editorial \
team. For errors or omissions, please contact us via the website. Clinical decisions should \
always be made with qualified healthcare professionals.*

*© {year} SBMA Research Agent · Next issue: {next_month}*
"""


class NewsletterGenerator:
    """Generates the monthly SBMA newsletter using the configured LLM backend."""

    def __init__(self):
        self.db = DBManager()

    def generate(
        self,
        new_articles: list[dict],
        novelty_scores: list[dict],
        clinical_trials: list[dict],
        future_conferences: list[dict],
        recent_conferences: list[dict],
        period_start: date,
        period_end: date,
    ) -> str:
        """Generate the newsletter Markdown.

        Args:
            new_articles: List of new article dicts (from NewArticleChecker).
            novelty_scores: List of novelty scoring dicts (from NoveltyScorer).
            clinical_trials: List of trial dicts (from NewsFetcher).
            future_conferences: List of future conference dicts.
            recent_conferences: List of recent conference dicts.
            period_start: Start of the reporting period.
            period_end: End of the reporting period.

        Returns:
            Full newsletter as a Markdown string.
        """
        period_label = period_start.strftime("%B %Y")
        today_str = date.today().strftime("%B %d, %Y")

        # Build score map
        score_map = {s.get("pmid", ""): s for s in novelty_scores}

        # Articles section for prompt
        articles_section = self._format_articles_for_prompt(new_articles, score_map)

        # Trials section
        trials_section = self._format_trials_for_prompt(clinical_trials)

        # Trials table rows
        trials_table = self._build_trials_table_rows(clinical_trials)

        # Conferences sections
        conferences_section = self._format_conferences_for_prompt(future_conferences)
        recent_conferences_section = self._format_conferences_for_prompt(recent_conferences)

        # Knowledge context (brief textbook summary)
        textbook = self.db.get_textbook_as_dict()
        knowledge_context = "\n".join(
            f"**{ch}**: {content[:500]}..."
            for ch, content in list(textbook.items())[:6]
        )

        # Pre-build the publication table rows for the prompt
        table_rows = self._build_publication_table_rows(new_articles)

        prompt = NEWSLETTER_PROMPT_TEMPLATE.format(
            today=today_str,
            period_label=period_label,
            start_date=period_start.strftime("%B %d, %Y"),
            end_date=period_end.strftime("%B %d, %Y"),
            article_count=len(new_articles),
            articles_section=articles_section,
            trials_section=trials_section,
            full_trials_table=trials_table,
            recent_conferences_section=recent_conferences_section,
            conferences_section=conferences_section,
            knowledge_context=knowledge_context or "Knowledge base not yet available.",
            full_publication_table=table_rows,
            year=date.today().year,
            next_month=self._next_month_label(period_end),
        )

        logger.info(
            f"Generating newsletter for {period_label} with {len(new_articles)} articles "
            f"and {len(clinical_trials)} trials (backend: {config.LLM_BACKEND})"
        )

        # Prepend system context into prompt so all backends receive it
        full_prompt = f"{NEWSLETTER_SYSTEM_PROMPT}\n\n{prompt}"

        newsletter_md = call_llm(
            prompt=full_prompt,
            mode="synthesis",
            json_mode=False,
            max_tokens=8000,
            temperature=0.7,
        )

        logger.info(f"Newsletter generated: {len(newsletter_md)} characters")
        return newsletter_md

    def _format_articles_for_prompt(
        self, articles: list[dict], score_map: dict
    ) -> str:
        if not articles:
            return "No new SBMA articles found this month."

        lines = []
        for i, art in enumerate(articles, 1):
            pmid = art.get("pmid", "")
            score = score_map.get(pmid, {})

            authors = art.get("authors", [])
            first_author = ""
            if authors:
                a = authors[0]
                first_author = a.get("name", "") if isinstance(a, dict) else str(a)

            novelty = score.get("novelty_score") or score.get("Novelty Score (1-10)", "N/A")
            category = score.get("category", "other")
            takeaway = score.get("key_takeaway") or score.get("Key Takeaway", "")
            new_info = score.get("new_information") or score.get("New Information", "")
            clinical_rel = score.get("clinical_relevance") or score.get("Clinical Relevance", "")

            lines.append(
                f"[{i}] PMID: {pmid} | DOI: {art.get('doi', 'N/A')}\n"
                f"Title: {art.get('title', 'Untitled')}\n"
                f"Authors: {first_author} et al.\n"
                f"Journal: {art.get('journal', '')} ({art.get('publication_year', '')})\n"
                f"Category: {category} | Novelty: {novelty}/10 | Clinical Relevance: {clinical_rel}\n"
                f"Key Takeaway: {takeaway}\n"
                f"New Information: {new_info}\n"
                f"Abstract: {(art.get('abstract') or '')[:600]}\n"
            )
        return "\n---\n".join(lines)

    def _format_trials_for_prompt(self, trials: list[dict]) -> str:
        if not trials:
            return "No active SBMA clinical trials found on ClinicalTrials.gov this month."
        lines = []
        for t in trials:
            phases = ", ".join(t.get("phase", [])) or "Not specified"
            interventions = ", ".join(t.get("interventions", [])) or "Not specified"
            lines.append(
                f"NCT: {t.get('nct_id', '')} | Status: {t.get('status', '')}\n"
                f"Title: {t.get('title', '')}\n"
                f"Phase: {phases} | Sponsor: {t.get('sponsor', '')}\n"
                f"Interventions: {interventions}\n"
                f"Start: {t.get('start_date', '')} | Completion: {t.get('completion_date', '')}\n"
                f"URL: {t.get('url', '')}\n"
            )
        return "\n---\n".join(lines)

    def _format_conferences_for_prompt(self, conferences: list[dict]) -> str:
        lines = []
        for c in conferences:
            lines.append(
                f"Conference: {c.get('name', '')}\n"
                f"Organizer: {c.get('organizer', '')}\n"
                f"Relevance: {c.get('relevance', '')}\n"
                f"URL: {c.get('url', '')}\n"
            )
        return "\n".join(lines)

    def _build_publication_table_rows(self, articles: list[dict]) -> str:
        rows = []
        for i, art in enumerate(articles, 1):
            authors = art.get("authors", [])
            first_author = ""
            if authors:
                a = authors[0]
                first_author = a.get("name", "") if isinstance(a, dict) else str(a)
            title = (art.get("title") or "")[:80]
            if len(art.get("title") or "") > 80:
                title += "..."
            rows.append(
                f"| {i} | {title} | {first_author} | "
                f"{art.get('journal', '')} | {art.get('publication_year', '')} | "
                f"{art.get('pmid', '')} | {art.get('doi', '')} |"
            )
        return "\n".join(rows) if rows else "| — | No new articles this month | — | — | — | — | — |"

    def _build_trials_table_rows(self, trials: list[dict]) -> str:
        rows = []
        for t in trials:
            phases = ", ".join(t.get("phase", [])) or "Not specified"
            interventions = ", ".join(t.get("interventions", [])) or "Not specified"
            rows.append(
                f"| {t.get('title', '')[:60]} | {phases} | "
                f"{interventions} | {t.get('status', '')} | "
                f"{t.get('nct_id', '')} |"
            )
        return "\n".join(rows) if rows else "| — | — | — | — | — |"

    def _next_month_label(self, period_end: date) -> str:
        if period_end.month == 12:
            return date(period_end.year + 1, 1, 1).strftime("%B %Y")
        return date(period_end.year, period_end.month + 1, 1).strftime("%B %Y")
