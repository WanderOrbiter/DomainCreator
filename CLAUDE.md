# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A single-file Python tool (`main.py`) that checks domain availability by querying each registry's RDAP server, and generates candidate domain names by combining character groups. Results are written to CSV.

## Run

```bash
python main.py
```

No dependencies beyond `requests`. Uses `concurrent.futures` (stdlib) for parallel RDAP queries. No tests, build, or lint step.

## Data files

- `domains.txt` — one domain **template** per line (see below). Lines with no group references are checked as-is.
- `result.csv` — UTF-8-sig output, **available domains only** (not every check result); columns `domain,status,http_status,registration_date`. Rewritten on every run.

`main()` expands every template in `domains.txt` into concrete domains, checks the whole list, and writes only `available` rows to the CSV.

## Architecture

Everything lives in `main.py`. Top-down flow:

1. **Config** (top of file) — `INPUT_FILE`, `OUTPUT_FILE`, `MAX_WORKERS`, `TIMEOUT`, `RETRIES`, then `CHAR_GROUPS` (described below).
2. **`RDAP_SERVERS`** — TLD → RDAP base URL. Only TLDs listed here are supported (`unsupported_tld` status otherwise).
3. **`check_domain(domain)`** — one RDAP lookup. `200` → `registered` (with `registration_date`), `404` → `available`, `429` → retry with exponential backoff, other statuses surfaced as `http_<code>`. Uses a module-level shared `requests.Session`.
4. **`expand_template(template, groups)`** — expands one `domains.txt` line into concrete domains (see below).
5. **`load_domains(filename)`** — reads `domains.txt`, expands each line via `expand_template`, dedupes preserving order.
6. **`main()`** — expands all templates, runs checks in a `ThreadPoolExecutor` (`MAX_WORKERS`), writes only `available` rows to CSV, prints summary counts.

### Domain templates and char groups

This is the non-obvious core. Each line of `domains.txt` is a **template**: literal text with embedded **char-group references**. When a character in the line matches a `CHAR_GROUPS` key, it expands to every entry of that group; otherwise it's kept as literal text. So a line with no references is checked as one literal domain, and a line like `orbioCV.com` expands to `orbioba.com`, `orbiobe.com`, ... (105 domains with the defaults).

A group maps a name to entries; a value is either a **string** (each char is one entry, for single-character placeholders) or a **list** (each string is one entry, for multi-character prefixes/suffixes).

A group's name determines its conventional type — name starts with `<` → **prefix** group (multi-character strings like `["io","ix"]`), ends with `>` → **suffix** group, otherwise → **core** group (`C` = consonants, `V` = vowels). The `<`/`>` are part of the group's *name*, used to reference it in a template (e.g. `<A` / `B>`). Position of a group's entries in the generated word is decided by where its reference appears in the template line, not the marker.

**Important:** group-name matching is case-sensitive and by exact key — `C` and `V` (uppercase) are the vowel/consonant placeholders; lowercase `c`, `v`, and any other letter are literal text.

Note the combinatorial explosion: `orbioCV.com` is 105 domains, and each additional group reference multiplies the total — every generated domain becomes a live RDAP request at runtime.

### RDAP status mapping

RDAP 404 is the signal for availability (`available`). Because the RDAP endpoint differs per TLD, availability is only meaningful for TLDs in `RDAP_SERVERS`.
