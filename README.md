# learn2pdf

Save a Microsoft Learn certification, course, learning path or module as PDF, one PDF per module, with a bookmark for every unit. Handy for offline study or for feeding into a local RAG / Obsidian setup.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
# Whole certification
python learn2pdf.py "https://learn.microsoft.com/en-us/credentials/certifications/<certification-name>/"

# Only list what it finds
python learn2pdf.py URL --dry-run

# Also save Markdown per module (for RAG / Obsidian)
python learn2pdf.py URL --markdown

# Several start URLs, custom output folder
python learn2pdf.py URL1 URL2 -o AB-900
```

### Options

| Option | What it does |
|---|---|
| `-o`, `--out` | Output folder (default: `learn-pdf`) |
| `--dry-run` | Only list modules and units, download nothing |
| `--markdown` | Also save a `.md` file per module |
| `--per-unit` | One PDF per unit instead of per module |
| `--keep-units` | Keep the separate per-unit files in `_units/` |
| `--combined` | Also make one big PDF with everything |
| `--parallel N` | Number of pages printed at once (default 4) |

## Output

```
learn-pdf/
├── 01-Module-title.pdf
├── 02-Module-title.pdf
└── ...
```

## Note

The downloaded content belongs to Microsoft Learn. This tool is meant for personal study use.

## Credits

Built with help from [Claude](https://claude.ai) (Anthropic).
