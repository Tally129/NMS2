# NMS Emergent Development Instructions

## Purpose

Emergent is a development accelerator for Natural Medical Solutions.

Emergent is NOT the production environment, source of production
authority, infrastructure owner, database owner, authentication owner,
or deployment authority.

The authoritative production system remains the existing NMS
application hosted on AWS EC2.

---

# 1. Authoritative Architecture

Preserve the existing NMS architecture.

Primary application:

- React frontend
- FastAPI backend
- PostgreSQL
- AWS EC2 production
- Existing AWS infrastructure and services
- Existing NMS authentication and authorization
- Existing NMS API conventions
- Existing Marketing OS architecture
- Existing audit and approval controls

Do not replace these systems with Emergent equivalents.

---

# 2. Development Workflow

Emergent must work only on an approved `emergent/*` Git branch.

Emergent must never directly modify:

- production EC2
- the production branch
- production databases
- production environment variables
- production secrets
- production AWS configuration

Expected workflow:

Emergent feature branch
→ GitHub
→ NMS code review
→ automated checks
→ integration testing
→ human approval
→ controlled merge
→ EC2 deployment

---

# 3. No Emergent Branding

Do not add any Emergent branding or attribution to application code
or user-facing output.

Prohibited examples include:

- "Built with Emergent"
- "Powered by Emergent"
- Emergent logos
- Emergent badges
- Emergent watermarks
- Emergent attribution links
- Emergent promotional text
- Emergent-hosted production URLs
- Emergent-specific UI
- generated-by-Emergent comments
- Emergent runtime dependencies unless explicitly approved

The finished application must use Natural Medical Solutions branding
only.

---

# 4. No Production Secrets

Never place real production credentials into source code.

Do not request, commit, print, or expose:

- AWS credentials
- database passwords
- JWT secrets
- encryption keys
- Stripe secrets
- Google Ads secrets
- Meta access tokens
- Microsoft Advertising credentials
- TikTok credentials
- SendGrid API keys
- OAuth client secrets
- refresh tokens
- private keys

Code must reference environment-variable names or approved secret
interfaces.

Example:

    token = os.environ["META_ACCESS_TOKEN"]

Never hard-code the actual token.

---

# 5. Marketing Provider Architecture

Advertising integrations must use a provider-neutral architecture.

Target providers include:

- Google Ads
- Meta Ads
- Microsoft Advertising / Bing
- TikTok Ads
- LinkedIn Ads
- Pinterest Ads
- Reddit Ads
- future providers

Do not build unrelated one-off architectures for each provider when a
shared provider interface can be used.

Provider-specific code should adapt external APIs into NMS canonical
models.

---

# 6. Financial Safety Boundary

AI must not have unrestricted financial authority.

The required architecture is:

AI Recommendation
→ deterministic Policy Engine
→ Budget Rules
→ Approval Rules
→ Human Approval
→ Provider Adapter
→ External Advertising Provider

Do not bypass this sequence.

Unless explicitly authorized by later production policy:

- external writes remain disabled
- automatic budget changes remain disabled
- automatic campaign creation remains disabled
- automatic publishing remains disabled
- human approval remains required

Approval alone does not automatically mean external execution.

---

# 7. Marketing Data Safety

Marketing systems must use marketing-safe data.

Do not place clinical or patient medical information into Marketing OS.

Examples of prohibited Marketing OS data include:

- diagnoses
- medical history
- clinical notes
- SOAP notes
- medications
- laboratory results
- treatment details
- medical record numbers
- protected health information

Marketing analytics should use approved marketing-safe identifiers,
campaign data, attribution data, and aggregate business outcomes.

---

# 8. Existing NMS Systems Must Be Preserved

Do not replace or recreate existing systems without reviewing the
existing implementation first.

Examples include:

- authentication
- authorization
- patient portal
- appointment workflow
- Content Strategist
- Campaign Center
- Marketing Command Center
- Marketing OS measurement
- attribution
- recommendation system
- approval ledger
- provider registry
- PostgreSQL models
- API wrapper
- frontend routing

Inspect existing contracts before implementing changes.

---

# 9. Search Intelligence Direction

The Marketing OS will eventually include Semrush-like capabilities,
including:

- SEO overview
- keyword research
- keyword gap
- competitor intelligence
- rank tracking
- technical site audit
- backlink intelligence
- content opportunities
- local SEO
- Search Console integration
- AI / LLM visibility

These features must integrate into the existing NMS Marketing OS
rather than becoming an unrelated standalone production platform.

---

# 10. Lead Generation Direction

The platform will include marketing-safe AI lead generation.

Expected flow:

Traffic / Campaign
→ Lead Capture
→ Abuse Protection
→ Qualification
→ Intent Scoring
→ Lead Opportunity
→ Appointment
→ Show
→ Purchase
→ Revenue Attribution

Do not use clinical information to score marketing leads.

---

# 11. Appointment Abuse Protection

Public appointment intake should eventually support layered abuse
protection such as:

- Cloudflare Turnstile
- honeypot
- rate limiting
- duplicate detection
- submission velocity checks
- validation
- privacy-safe risk scoring
- optional email verification

Blocked bot traffic must not inflate marketing lead or conversion
metrics.

---

# 12. Coding Rules

Follow the existing repository structure and style.

Prefer:

- small scoped changes
- deterministic behavior
- explicit error handling
- tests
- backwards-compatible API changes
- provider-neutral interfaces
- reusable components

Avoid:

- unnecessary rewrites
- broad refactors unrelated to the feature
- replacing working infrastructure
- adding dependencies without justification
- changing unrelated files
- silently changing API contracts

---

# 13. Git Safety

Never use destructive or broad Git commands in automated changes.

Do not use:

    git add .
    git reset --hard
    git clean
    git checkout -- .
    blanket git restore operations

Stage only intended files.

Do not modify unrelated dirty work.

---

# 14. Deployment

Emergent does not deploy NMS production.

Emergent may produce code and testable feature branches.

Production deployment remains controlled through the established NMS
EC2 deployment process.

---

# 15. Definition of Done

An Emergent-generated feature is not production-ready merely because
it renders successfully.

Before production integration it must pass, as applicable:

- code review
- branding scan
- secret scan
- dependency review
- backend tests
- frontend build
- API contract verification
- authorization verification
- privacy review
- Marketing OS safety checks
- provider-write safety checks
- human approval

EC2 remains authoritative.
