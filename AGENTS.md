# AGENTS.md

Instructions for coding agents working in this repository
(`government-data/bi-superset`, public). Adapted from `quality-sdk`'s
`AGENTS.md` on 2026-11-25: the same way of working, for this repo.

## What this is

`bi-superset`: the BI module of Quality Data, installed by `quality-sdk`
(`qd module add bi-superset`). Apache Superset draws the quality
indicators, which it reads from the lake's gold layer through Trino
(`sql-query`, provided by `query-trino`), as the person who looks at them.

- `image/`: the module's image, `apache/superset` pinned by digest and
  extended with what it lacks (the Trino driver, the OIDC client library,
  the PostgreSQL driver, the module's configuration).
- `config/`: `superset_config.py` (sign-in with the core's OIDC provider,
  roles from its claim, the connection mutator that exchanges the person's
  token for Trino, caches per person).
- `compose.yml` and `module.yaml`: what the installation's agent runs and
  what the module asks for at `module add`.
- `tools/verify/`: scripts that check external behaviour before code
  builds on it, and the module's check on a test installation.

The design lives in the decisions of the core (`government-data/core`,
decision 0089, "Superset draws the quality indicators") and of
`quality-sdk` (0002 modules, 0009 what a module gets at `module add`).
**Decisions are internal: never committed, pushed or published here.**
Code comments may name a decision by number, never copy its content.

## Before you change anything

1. **Find the decision and its step.** This repository carries out core
   decision 0089's steps 8 (the module) and 9 (the dashboards). Read the
   decision's **Decision** and **Implementation**: they name the files and
   the check that says a step is done.
2. **Follow the decision; do not redesign it in code.** If the code needs
   something the decision does not say, or contradicts it, stop and say so.
   An Open entry not yet ruled is not built.
3. **Verify external behaviour first.** Before building on what Superset,
   Flask-AppBuilder, Trino or Valkey do, write or run a script in
   `tools/verify/` and record the result in the decision (date, version,
   what was found). The core's `tools/verify/superset_*.sh` (decision
   0089's V1 to V6) already verified the base.

## Architecture patterns

- **Superset never reads the lake.** Its only data source is one Trino
  connection to `query-trino`'s internal entry point (mTLS), catalog
  `gold`, read-only. Its metadata database holds no indicator.
- **Every query runs as the person.** The connection mutator exchanges the
  person's token (or the core's guest token) at the core's provider for a
  Trino token; the core's permissions apply in Trino's row filter. The
  exchanged tokens live in the process's memory only, never in Valkey.
- **No secret in an image, a package or a log.** Secrets reach the
  containers as Compose file secrets (`/run/secrets/<name>`), written by
  the installation's agent; the configuration reads `*_FILE`.
- **Shipped dashboards are files.** Superset's assets export format,
  normalised and deterministic, imported with overwrite by `superset-init`
  at install and every update, matched by UUID.
- **The module is removable.** Remove keeps its database and Valkey
  volume; only purge deletes them, after a backup (quality-sdk 0009).

## Data rules

- **No personal data** in logs, fixtures, examples or documentation; the
  username Superset stores is the account id. Synthetic rows only.
- **Secrets** never go in the repository, a log, a commit or an image.
- **Never real cloud accounts in development or tests.** Tests use fakes,
  stand-ins or local containers. Publishing to ECR runs only from the
  release workflow; `terraform apply` is run by a person.
- **Do not install on the pilot.** The module's check runs on a test
  installation with `quality-sdk`'s local verify harness.

## Language

**English only. Nothing in Spanish** in code, identifiers, file names,
comments, documentation, commit messages, pull requests and issues. The
only Spanish is text people read in the product in Spanish: the menu
label (`es`) and the dashboards' Spanish titles and labels.

## Size limits

Targets, then hard limits that fail CI:

- **Python file** 400, hard 800 lines; **shell script** 300, hard 600.
- **Function** 60, hard 100 lines.
- **A change**: at most about 400 diff lines without generated files, one
  step at a time.

Above the target, split when you touch it. Never add an exception: split.

## Checks before a commit

```sh
tools/check.sh          # shellcheck, Python syntax and lint, YAML, sizes
```

## Do not

- Do not add a service decision 0089 does not name (Celery workers are not
  shipped, Open 5).
- Do not weaken a test, a lint or a check to make it pass.
- Do not commit, quote or link a decision in anything public.
- Do not copy data from an organisation into the repository, a fixture or
  a prompt.

## Builds on this machine

This machine is WSL with 16 GB and one disk. Every agent follows these
rules, with no exception for "a quick check":

- **One build or verification at a time, on the whole machine.** Before
  any image build or script in `tools/verify/`, check that no compiler is
  running (`pgrep -x rustc`, `pgrep -x cc1plus`) and wait if one is.
  Never use `pgrep -f`: it matches its own shell.
- **Clean up what you start.** Remove your `qd-verify-…` containers,
  networks and volumes when a script ends, also when it fails, in a trap.
- **If the machine slows down** (load above 8 in `uptime`), stop your own
  work by its PID and tell the user; do not start anything else.
