# Architect profession (example plugin)

Install into Arka:

```bash
profession install /path/to/arka/src/arka/professions/examples/architect
# or
profession install <git-url>
```

Then:

```bash
profession ask architect What is passive house design?
profession sources architect
```

Manifest fields: see `profession.json`. Optional `project_dir` points at a local repo for codebase indexing.
