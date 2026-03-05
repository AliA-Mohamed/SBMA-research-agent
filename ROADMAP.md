# SBMA Research Agent — Phased Roadmap

## Current State (2026-03-05)

- 993 articles in DB (1968-2026), 86.5% with fulltext
- 946/993 processed (95.3%), 47 unprocessed
- 10,261 knowledge entries across 13 types
- 12 textbook chapters generated (4 are stubs)
- Weekly monitor: implemented but never run
- Supabase + Lovable frontend: built but showing stale/inflated numbers
- Contamination: 41 knowledge entries + 8/12 textbook chapters contain polymer science content (sulfobetaine methacrylate, also abbreviated "SBMA")

---

## Phase 1: Clean V1 for Scientists (Target: publish to GitHub + live site)

The goal is a **credible, clean, useful resource** that an SBMA researcher would bookmark. Everything must be accurate — no contamination, no inflated numbers, no broken features.

### 1.1 Purge contamination from knowledge base
- **Delete the 41 contaminated knowledge entries** from extracted_knowledge (those containing polymer/material science terms: sulfobetaine, methacrylate, zwitterionic, polymer, nanoparticle, hydrogel, antimicrobial peptide, biofilm, antifouling, transdermal, microneedle, nanocarrier)
- **Identify and remove source articles** — find PMIDs that produced these entries and are clearly non-SBMA-disease articles. Add them to false_positive_pmids.txt and delete from DB
- Write a one-time script: `scripts/purge_contamination.py`

### 1.2 Regenerate textbook chapters (clean synthesis)
- **Switch synthesis model to Claude** (Opus or Sonnet) — Gemini Flash Lite is too weak for synthesis and let contamination through
- **Re-run textbook builder from scratch** on the cleaned knowledge base
- Focus on the 4 stub chapters (Ch 10, 12 especially) getting proper depth
- Fix the duplicate header bug (e.g., "## Chapter 10" appears twice in current output)
- Verify zero contamination in output by grepping for polymer terms
- **Cap: ~2-3 hours of LLM processing time**

### 1.3 Process remaining 47 articles
- Run `scripts/run_textbook_builder.py` to completion
- These are scattered across 2000-2026, filling small gaps
- ~1 hour with Gemini extraction

### 1.4 Fix author h-index computation
- The h-index calculation exists in field_analytics.py but produces all zeros
- Debug and fix — the citation_count field on articles is populated, so h-index per author should be computable from the DB
- Re-run analytics to regenerate author stats

### 1.5 Re-run analytics with clean data
- Regenerate all outputs in `outputs/analytics/`
- Publication timeline, journal distribution, author network, citation analysis, topic evolution, article type trends
- Re-run gap analysis with Claude (not Gemini) for higher-quality output

### 1.6 Run weekly monitor for the first time
- Execute `scripts/run_weekly_monitor.py` to validate the pipeline
- Fix any bugs that surface
- Generate first weekly digest in `outputs/weekly_reports/`
- This proves the system is alive and current

### 1.7 Re-export to Supabase
- Run `scripts/export_to_supabase.py` with all cleaned data
- Update stats_overview with accurate counts (993 articles, not 1,518)
- Include gap analysis export
- Verify all tables are populated correctly

### 1.8 Update README and Lovable frontend prompt
- README: accurate description of what the system does, actual numbers, how to run each script
- Update lovable-prompt.md with corrected article counts and knowledge_type values (no longer just "finding")
- Add a "Data last updated: YYYY-MM-DD" indicator to the frontend

### 1.9 Final QA pass
- Grep all textbook chapters for contamination terms — must be zero hits
- Spot-check 20 random knowledge entries for accuracy
- Verify every script in `scripts/` runs without error
- Verify dashboard loads and shows correct data
- Clean git history, push to GitHub

### Phase 1 Deliverables
- Clean, accurate textbook (12 chapters, zero contamination)
- 993 curated articles with 10K+ knowledge entries (properly typed)
- Working analytics suite with correct author h-indices
- First weekly monitoring report
- Live Supabase-backed website with accurate numbers
- Public GitHub repo with clear README

---

## Phase 2: Structured Data for Power Users (2-3 weeks after V1)

Move from "readable textbook" to "queryable research platform." This is what makes it more useful than just reading reviews.

### 2.1 Clinical trial registry table
- New DB table: `clinical_trials`
  - `nct_id`, `trial_name`, `phase`, `drug/intervention`, `mechanism_of_action`, `status` (recruiting/completed/terminated), `primary_outcome`, `result_summary`, `n_enrolled`, `year_start`, `year_end`, `sponsor`, `source_pmids`
- Extract from existing knowledge base + pull from ClinicalTrials.gov API
- Known trials to seed: leuprolide (Japan-approved), CRECKET (creatine), BVS-857 (IGF-1 mimetic), dutasteride, mexiletine, NIPPV
- Add `/trials` page to frontend and Supabase table
- **Why scientists care:** Instant landscape view of what's been tried, what worked, what failed

### 2.2 Biomarker tracker table
- New DB table: `biomarkers`
  - `name`, `type` (diagnostic/prognostic/pharmacodynamic), `validation_level` (exploratory/qualified/validated), `sensitivity`, `specificity`, `used_in_trials` (NCT IDs), `source_pmids`, `notes`
- Extract from Chapter 9 content + knowledge entries typed as "biomarker"
- Known biomarkers: serum creatinine, CK, IGF-1, neurofilament light chain (NfL), CMAP, MUNIX, muscle MRI T2, AR protein levels
- Add `/biomarkers` page to frontend
- **Why scientists care:** Planning a trial? You need to know which endpoints are validated

### 2.3 Knowledge graph relationships
- Populate the `supports` and `contradicts` fields in extracted_knowledge
- Run a targeted extraction pass over high-impact articles (top 100 by citation)
- Store as PMID pairs with relationship type
- Visualize as an interactive network on the frontend
- **Why scientists care:** "What evidence contradicts the muscle-first hypothesis?" becomes answerable

### 2.4 Improve knowledge type distribution
- The "finding" type (2,241 entries, 22%) is a catch-all — re-classify these into proper types
- Update extraction prompt with better examples and stricter typing
- Re-extract a sample of 100 articles to validate improvement
- Bulk re-classify existing "finding" entries using LLM

### 2.5 Add search across knowledge base
- Full-text search over knowledge entry summaries and details
- Expose via dashboard API and frontend search bar
- SQLite FTS5 for local, pg_trgm for Supabase
- **Why scientists care:** "What do we know about TDP-43 in SBMA?" should be a 2-second query

### 2.6 Schedule weekly monitor (cron)
- Set up cron job or launchd plist to run weekly monitor every Monday
- Auto-export new data to Supabase after each run
- Email/webhook notification when new high-novelty articles found

### Phase 2 Deliverables
- Structured clinical trial registry with outcomes
- Biomarker validation tracker
- Knowledge graph with supports/contradicts relationships
- Searchable knowledge base
- Automated weekly monitoring

---

## Phase 3: Pharma & Regulatory Value (4-6 weeks after V1)

Make the platform useful for drug developers, regulatory affairs, and HTA submissions.

### 3.1 Drug pipeline visualization
- New table: `therapeutic_pipeline`
  - `drug_name`, `mechanism`, `target`, `stage` (preclinical/Phase I/II/III/approved), `company/lab`, `model_systems_tested`, `key_results`, `source_pmids`
- Visual pipeline chart: x-axis = stage, grouped by mechanism of action
- Categories: AR degradation (PROTACs), gene silencing (ASOs/siRNA), hormonal (leuprolide), autophagy enhancers, muscle-targeted, epigenetic
- **Why pharma cares:** Competitive intelligence in one view

### 3.2 Natural history structured dataset
- Extract from case series and longitudinal studies:
  - Age of onset distributions (mean, range, by CAG repeat length)
  - Progression milestones (wheelchair use, ventilation, death)
  - Genotype-phenotype correlations (CAG length vs onset, severity)
  - Survival curves
- New table: `natural_history_data`
- **Why regulators care:** Required for regulatory submissions and trial design

### 3.3 Epidemiology structured dataset
- New table: `epidemiology_data`
  - `country/region`, `prevalence`, `incidence`, `sample_size`, `method`, `year`, `source_pmid`
- Map visualization of global prevalence data
- **Why pharma cares:** Market sizing for rare disease business cases

### 3.4 Evidence grading
- Assign each knowledge entry a study design level:
  - RCT > cohort > case-control > case series > case report > in vitro > animal model > expert opinion
- Add `evidence_level` field to extracted_knowledge
- Filter/sort by evidence level in frontend
- **Why regulators care:** Distinguishes signal from noise

### 3.5 Outcome measure inventory
- New table: `outcome_measures`
  - `name`, `type` (clinician-reported/patient-reported/biomarker/imaging), `validated_in_sbma` (bool), `mcid` (minimal clinically important difference), `trials_used_in`, `psychometric_properties`, `source_pmids`
- Known measures: ALSFRS-R, SBMA-FRS, hand grip dynamometry, 6MWT, SBMA-HI, quantitative muscle MRI, CMAP, MUNIX
- **Why trialists care:** Endpoint selection is a make-or-break trial design decision

### Phase 3 Deliverables
- Visual drug development pipeline
- Structured natural history and epidemiology datasets
- Evidence-graded knowledge base
- Outcome measure inventory for trial designers

---

## Phase 4: Patient & Community Features (ongoing)

### 4.1 Plain-language chapter summaries
- For each textbook chapter, generate a patient-friendly summary (8th-grade reading level)
- "What does this mean for me?" framing
- Store as separate textbook_sections entries with a `audience: "patient"` tag

### 4.2 Clinical care guideline extraction
- Parse published CPGs (Canadian CPG: PMID:37715620, Japanese guidelines)
- Generate structured care checklists: symptom monitoring schedule, recommended tests, specialist referrals, contraindicated treatments
- New page: `/care-guide`

### 4.3 Research lab & clinical site directory
- Extract institutions from author affiliations
- Map active research groups: lab name, PI, institution, focus area, recent publications
- Identify clinical trial sites from ClinicalTrials.gov
- New page: `/find-experts`

### 4.4 Multilingual summaries
- SBMA has notable prevalence in Japan, with growing literature from Italy, Brazil, China
- Generate key summaries in Japanese, Italian, Portuguese, Chinese
- Start with Chapter 4 (Clinical Features) and Chapter 8 (Therapeutics)

### Phase 4 Deliverables
- Patient-friendly textbook summaries
- Clinical care quick-reference guide
- Expert/lab directory with map
- Multilingual key content

---

## Phase 5: Platform Maturity (3-6 months)

### 5.1 API for programmatic access
- REST API over Supabase PostgREST (already available via Supabase)
- Document endpoints, add rate limiting
- Enable researchers to query the knowledge base programmatically

### 5.2 Citation alerts & personalized feeds
- Users can "watch" topics, authors, or mechanisms
- Email digest when new relevant articles are found by weekly monitor

### 5.3 Community contributions
- Allow researchers to flag errors, add annotations, or suggest missing articles
- Moderated submission pipeline

### 5.4 Textbook versioning & changelog
- Track diffs between textbook versions
- "What's new since you last visited" feature
- DOI for each textbook version (via Zenodo)

### 5.5 Integration with other rare disease platforms
- NORD, Orphanet, OMIM cross-links
- Structured data export in standard formats (RDF, JSON-LD)
