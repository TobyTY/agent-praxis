# Repository settings (applied by the maintainer)

These settings live in GitHub, not in the repository, so they are listed here to apply by
hand (Part O.3). Tick each one when done.

- [ ] Branch protection on `main`: pull requests required, required status checks
      (`ci / freshness`, `ci / hooks (*)`, `ci / core (*)`, `codeql`), linear history,
      no force pushes, no deletions.
- [ ] Secret scanning with push protection: on.
- [ ] Private vulnerability reporting: on.
- [ ] Dependabot alerts and security updates: on.
- [ ] Discussions: on.
- [ ] Topics: `claude-code`, `agent-skills`, `ai-agents`, `procedural-memory`,
      `llm-security`, `developer-tools`.
- [ ] Actions: "Read repository contents" as the default workflow permission; require
      approval for workflows from first-time contributors.
- [ ] Before the first release (Phase 1): a `release` environment with required reviewers,
      and a PyPI Trusted Publisher for `agent-praxis` bound to `release.yml`.
