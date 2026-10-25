# Changelog

Notable changes to elsevier-stream. Versions follow [semantic versioning](https://semver.org/).

## Unreleased

### Added

- elsevier-stream 0.1.0, modelled on [pubmed-stream](https://github.com/melhzy/pubmed-stream) for Elsevier's APIs: `search` sizes a Scopus search, or a ScienceDirect search with `--sciencedirect`; `download` saves each match's Scopus record (abstract, authors, affiliations, keywords, index terms, references, citation count) as `<Scopus ID>.json`, with the full text of ScienceDirect articles where the key and network are entitled; `list` reads them back compactly and finds the most cited works; `export` writes BibTeX or RIS; `status` shows which APIs the key opens and the weekly quotas left; `init` prepares a research folder for Claude Code, Codex and Gemini CLI and saves the key; `mcp` serves seven tools to AI assistants, with progress for downloads.
- A plugin for Claude Code and Codex, in `plugins/elsevier-stream`, with the instructions as the skill `elsevier-search`; Claude Code asks for the API key at install.
- The key comes from `ELSEVIER_API_KEY`, the plugin, `~/.elsevier-stream.json` or a `.env` file; full texts tried after a refusal are skipped for the rest of a download, and Scopus's paging of reference lists is handled as it actually behaves.
