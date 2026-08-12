---
name: readme-engineering
description: Use this skill whenever the user asks to write, generate, review, restructure, audit, or improve a README.md for any software project, in any language or framework. Trigger on requests like "write a README", "review my README", "README นี้ดีไหม", "ช่วยทำ README ให้หน่อย", "clean up my documentation", or when the user shares project files (package.json, requirements.txt, pyproject.toml, source tree, etc.) and wants documentation produced from them. Always prefer this skill over writing README content from general knowledge alone — it defines the required inspect-before-writing workflow, the truthfulness rules that prevent inventing features or claims, the standard information architecture, and the quality/anti-pattern checklist that separates professional documentation from a developer's raw notes.
---

# README Engineering

Technology-agnostic methodology for producing `README.md` files that are professional, accurate, and scannable. Do not assume any specific language, framework, database, or deployment platform unless the project provides that information as evidence.

## Core principle

A README is not a dump of technical information — it is the information architecture for the project. Order content the way a new reader naturally asks questions:

```
What is this? → Why does it exist? → What can it do? → How does it work?
→ How do I run it? → How do I use it? → How do I configure it?
→ How do I develop it? → How do I operate it? → What are its limitations?
→ Where is it going?
```

Optimize for progressive disclosure: never expose deep implementation detail before the project's purpose and capabilities are established.

## Step 1 — Identify the audience(s)

A README can serve several audiences; structure it so each can find what it needs quickly.

| Audience           | Needs to know                                                                                 |
| ------------------ | --------------------------------------------------------------------------------------------- |
| Product / Business | What it does, who it's for, main capabilities, deployment model, maturity                     |
| Developer          | Install, run, configure, API/CLI usage, project structure, dev workflow, testing              |
| DevOps / Infra     | Runtime requirements, deployment, env vars, storage, networking, health checks, observability |
| Maintainer         | Architecture, design decisions, conventions, testing strategy, contribution flow, roadmap     |

## Step 2 — Inspect before writing

Never rewrite a README blindly. Before producing anything, gather evidence:

1. Existing README and any `docs/`
2. Project structure and entry points
3. Configuration sources (env vars, config files, CLI flags)
4. Deployment mechanism (Dockerfile, CI/CD, manifests)
5. APIs, CLI commands, or UI surfaces
6. Persistence and storage
7. External dependencies
8. Testing strategy (or its absence)
9. Architecture and processing flow
10. Security mechanisms
11. Known limitations and operational constraints

**Never invent** features, APIs, config variables, supported platforms, performance numbers, security guarantees, test coverage, architecture components, or roadmap items. If something can't be verified from evidence, mark it as unknown or leave it out.

## Step 3 — Apply the truthfulness hierarchy

When a claim needs backing, prefer higher sources over lower ones:

```
Actual source/configuration
    ↓
Existing project documentation
    ↓
Verified runtime behavior
    ↓
Reasonable inference
    ↓
General knowledge
```

Never convert an assumption into a stated fact.

- Bad: "Supports unlimited file uploads."
- Better: "Upload limits are configurable through the application's upload-size configuration."

Never claim "production ready", "enterprise ready", "high performance", "secure", "scalable", "unlimited", or "zero downtime" unless the implementation and gathered evidence actually support it.

## Step 4 — Build the structure

Default section order — include only sections that provide real value, don't force every one into every project:

```
Project Identity → Overview → Key Features → Architecture → Technology Stack
→ Requirements → Quick Start → Configuration → Authentication/Security → Usage
→ API/CLI Reference → Processing/Data Flow → Development → Testing
→ Project Structure → Deployment/Operations → Troubleshooting → Limitations
→ Roadmap → Contributing → License
```

### Section-by-section rules

**Project Identity** — Name, one-line value proposition (`What + Purpose + Important characteristic`), badges, short description. Never open with the tech stack ("Built with Framework X...") — purpose comes before implementation.

**Badges** — Only ones that communicate verifiable status (build, test, coverage, release, license). Never decorative or unverifiable badges.

**Overview** — What it is, what problem it solves, primary use case, what makes it useful. A reader should understand the project without reading implementation details.

**Key Features** — Group by capability, not by implementation detail. "Supports asynchronous background processing" beats "Uses asynchronous Python functions."

**Architecture** — Only if there's meaningful internal structure. Show the flow (Input → Interface → Application/Processing → Domain/Services → Infrastructure → Persistence/External), and use a diagram only when there are real multi-component interactions. Keep three levels distinct: README = what/why, `docs/` = how, source = exactly how.

**Technology Stack** — A table of layer → technology → purpose. Only list technologies that help readers understand architecture or operation — not every dependency.

**Requirements** — Separate Required / Recommended / Optional, and distinguish "tested on" from "supported." Only say "Supported" when the project actually intends to support that environment.

**Quick Start** — Shortest successful path: Install → Configure → Run → Verify. Lead with the recommended deployment method; push advanced configuration elsewhere.

**Configuration** — A table: Variable | Default | Required | Description. Group by area (Application, Database, Storage, Security, Processing, Logging) when there are many. Show real defaults, flag secrets clearly, explain units and valid values — never expose real secret values. If multiple config sources exist, document precedence order (e.g., CLI args → env vars → config file → DB settings → defaults) — only the layers that actually exist.

**Security** — Split "Current Security Controls" (what's implemented) from "Production Recommendations" (what's advised). Never describe a recommendation as an implemented control.

**Usage** — Simplest successful example first (Request→Response for APIs, Command→Output for CLIs, Start→Open→Workflow for web apps). Link to detailed docs rather than listing every example.

**API/CLI Reference** — Organize by domain (Authentication, Users, Projects, …), not by source file. For key endpoints: method, path, auth, purpose, params, request/response example, error behavior. Don't duplicate a full OpenAPI spec inline — link to it if it exists.

**Processing/Data Flow** — For multi-stage pipelines (AI, ETL, media, background jobs): show the stage flow and call out async behavior, queueing, retries, timeouts, caching, and failure recovery.

**Data Lifecycle** — For systems handling files/jobs/messages: Created → Processing → Completed/Failed → Retention → Cleanup. State where data lives, how long, what's deleted, and whether persistence survives container recreation.

**Development** — Local setup, dev server, formatting, linting, type checking, tests, build, debugging. Keep separate from production deployment instructions.

**Testing** — Distinguish automated / manual / integration / e2e / performance testing. If automated tests don't exist, say so plainly but without unnecessarily negative wording: prefer "Automated test coverage is currently limited; manual verification covers the primary workflows" over "No tests."

**Project Structure** — Annotate the tree with what each top-level directory is for; don't paste raw `tree` output or document every trivial file. It should help a new developer find where to make a change.

**Deployment/Operations** — Container deployment, env config, persistent storage, networking, health checks, resource requirements, scaling, backups, logging, monitoring, restart/failure behavior. Split Development vs Production deployment when they differ meaningfully.

**Observability** — Document what currently exists (logs, metrics, traces, health checks, alerts). Put anything incomplete in the roadmap instead of implying it's already there.

**Troubleshooting** — Only problems likely enough to justify documenting, in Symptoms → Cause → Solution format. Prioritize install failures, config mistakes, dependency issues, runtime failures, resource/network/deployment problems. Move specialized cases to separate docs.

**Limitations** — State them plainly (single-node, local filesystem dependency, scaling ceiling, missing tests, unsupported platforms). Clearly-stated limitations increase trust rather than undermining it.

**Roadmap** — Group by maturity (Completed / Current / Planned / Future), describe evolution rather than wishlist items, and don't promise dates that aren't committed.

**Enterprise Readiness** (when relevant) — Judge against architecture, security, reliability, scalability, observability, testing, deployment, data management, documentation, operations — never label something "enterprise-ready" just because it uses modern technology.

## Step 5 — Keep the README focused

Move detail out of the README into `docs/` when a section gets long, environment-specific, or covers advanced deployment, extensive API reference, troubleshooting runbooks, or complex architecture:

```
README.md
docs/
├── architecture.md
├── installation.md
├── configuration.md
├── api.md
├── deployment.md
├── operations.md
├── troubleshooting.md
└── development.md
```

The README is the entry point into these documents, not a replacement for them.

## Reviewing or refactoring an existing README

Don't rewrite immediately — work through this sequence first:

1. Inspect the existing README
2. Inspect project evidence (Step 2 above)
3. Identify audiences
4. Identify current information architecture
5. Identify missing information
6. Identify duplicated information
7. Identify inaccurate or stale information
8. Design the improved structure
9. Rewrite content
10. Validate technical claims
11. Validate commands and paths
12. Final readability pass

When there's too much information already, classify every existing section rather than deleting wholesale:

```
Is this necessary for understanding or using the project?
    ├── Yes → keep in README
    └── No
         ├── Useful advanced info → move to docs/
         ├── Implementation detail → move to source comments
         └── Historical/obsolete → remove
```

## Writing style

Use short paragraphs, descriptive headings, tables where structured data helps, code blocks for executable commands, diagrams for real architecture, consistent terminology, and concrete examples. Avoid marketing language, long intro essays, excessive emoji, vague claims, unexplained acronyms, and unnecessary mentions of which AI tool wrote the documentation.

## Anti-patterns to avoid

- **Technical dump** — listing every library/file without explaining why it matters
- **Feature dump** — features listed flat with no grouping or priority
- **Installation wall** — pages of setup commands before the project is even explained
- **Environment-specific README** — instructions that only work on one developer's machine
- **Unsupported claims** — "production ready", "secure", "scalable" etc. without evidence
- **Copying source code** — reproducing large code blocks instead of linking to it
- **Excessive API docs** — hand-duplicating a full spec that already exists elsewhere
- **Historical notes** — debug logs, workarounds, or personal notes left in the README
- **AI-generated noise** — unnecessary statements about which AI model wrote the docs

## Final validation checklist

Before delivering a README, confirm:

```
[ ] Project purpose is immediately clear
[ ] Primary audience is supported
[ ] Key features are grouped, not dumped
[ ] Architecture is understandable (if included)
[ ] Technology stack is concise, not exhaustive
[ ] Requirements are explicit (required/recommended/optional)
[ ] Quick Start actually works, shortest path first
[ ] Configuration is documented in a table, no real secrets exposed
[ ] Authentication/security is documented, controls vs. recommendations separated
[ ] API/CLI usage is clear
[ ] Data lifecycle is documented where relevant
[ ] Development workflow is documented separately from deployment
[ ] Testing status is stated honestly
[ ] Project structure explains architecture, not every file
[ ] Deployment and operational concerns are documented
[ ] Troubleshooting is focused, not exhaustive
[ ] Limitations are acknowledged
[ ] Roadmap is separated from current capabilities
[ ] Detailed/advanced material has been moved to docs/
[ ] No obsolete or unverified information remains
[ ] No unsupported claims remain
[ ] Commands and paths have been verified against the project
[ ] Terminology is consistent throughout
```

## Output requirements

1. Base every claim on gathered evidence, not assumption — flag anything that needs the user's verification.
2. Preserve verified facts from any existing README rather than discarding them.
3. Improve the information architecture before adding new content.
4. Favor clarity and progressive disclosure over documentation volume.
5. Separate user-facing docs from implementation detail; push advanced material to `docs/`.
6. Optimize the first screen for fast comprehension and make Quick Start genuinely the shortest path to a working run.
7. Document production concerns honestly, without overstating project maturity.

The result should read like documentation maintained by a professional engineering team — not a collection of developer notes.
