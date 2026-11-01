#!/usr/bin/env python3
"""
learn2pdf.py - Save a Microsoft Learn certification / course / learning path / module as PDF.

Setup (once):
    pip install playwright pypdf
    playwright install chromium

Usage:
    python learn2pdf.py "https://learn.microsoft.com/en-us/credentials/certifications/copilot-and-agent-administration-fundamentals/"
    python learn2pdf.py URL --dry-run        # only list what it found
    python learn2pdf.py URL --markdown       # also save one .md per module (handy for RAG/Obsidian)
    python learn2pdf.py URL1 URL2 -o AB-900  # several start URLs, custom output folder

Output (default): one PDF per module, nothing else
    <out>/01-Module-title.pdf
    <out>/02-Module-title.pdf ...
Optional:
    --per-unit     one PDF per unit (chapter) instead: <out>/01-03-unit-name.pdf
    --markdown    <out>/NN-Module-title.md next to each PDF
    --keep-units   keep the per-unit files in <out>/_units/
    --combined     also <out>/<out>-complete.pdf with everything
"""
import argparse
import asyncio
import logging
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.async_api import async_playwright
from pypdf import PdfWriter

logging.getLogger("pypdf").setLevel(logging.ERROR)  # hide harmless "Object count" warnings

# Hide site chrome, cookie banner, feedback widgets etc. so only the lesson text gets printed
HIDE_CSS = """
header, footer, nav, aside,
[role="banner"], [role="contentinfo"], [role="navigation"],
#ms--site-header, #ms-cookie-banner, .wcp-consent, #wcpConsentBannerCtrl,
.uhf-container, #left-container, #ms--additional-resources, #affixed-left-container,
[data-bi-name="feedback-section"], [data-bi-name="unit-feedback"],
.feedback-section, .action-container, .next-section, .page-actions,
button { display: none !important; }
main, #main, #main-column { width: 100% !important; max-width: 100% !important;
    margin: 0 !important; padding: 0 !important; }
"""

# Remove the "Next unit: ..." heading (and the button after it) at the bottom of each unit
REMOVE_NEXT_UNIT_JS = """
() => {
  for (const h of document.querySelectorAll('h2, h3')) {
    if (/^\\s*Next unit/i.test(h.textContent)) {
      let el = h;
      while (el) { const nxt = el.nextElementSibling; el.remove(); el = nxt; }
    }
  }
}
"""

RE_COURSE =re.compile(r"/training/courses/[^/]+/$")
RE_PATH = re.compile(r"/training/paths/[^/]+/$")
RE_MODULE = re.compile(r"/training/modules/[^/]+/$")


def clean(url: str) -> str:
    """Drop query/fragment and make sure the path ends with '/'."""
    p = urlparse(url)
    path = p.path if p.path.endswith("/") else p.path + "/"
    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def uniq(items):
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def safe(name: str, maxlen: int = 80) -> str:
    return re.sub(r"[^\w\-]+", "-", name).strip("-")[:maxlen] or "untitled"


async def links_on(page, url):
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(1500)  # let late-loading lists render
    hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    return [clean(h) for h in hrefs if "learn.microsoft.com" in h]


async def find_modules(page, start_url):
    """Expand a certification/course/path/module URL into an ordered list of module URLs."""
    url = clean(start_url)
    if RE_MODULE.search(url):
        return [url]

    links = await links_on(page, url)
    if RE_PATH.search(url):
        return uniq(l for l in links if RE_MODULE.search(l))

    # certification / course / other page: find learning paths (or courses) first
    paths = uniq(l for l in links if RE_PATH.search(l))
    if not paths:
        for course in uniq(l for l in links if RE_COURSE.search(l)):
            paths += [l for l in await links_on(page, course) if RE_PATH.search(l)]
        paths = uniq(paths)

    modules = []
    for p in paths:
        print(f"  path: {p}")
        modules += [l for l in await links_on(page, p) if RE_MODULE.search(l)]
    if not paths:  # page links modules directly
        modules = [l for l in links if RE_MODULE.search(l)]
    return uniq(modules)


async def find_units(page, module_url):
    links = await links_on(page, module_url)
    title = re.sub(r"\s*-\s*Training.*$", "", await page.title())
    units = []
    for l in links:
        if l.startswith(module_url):
            rest = l[len(module_url):].strip("/")
            if rest and "/" not in rest and re.match(r"\d+-", rest):
                units.append(l)
    units = uniq(units)
    units.sort(key=lambda u: int(re.match(r"(\d+)", u[len(module_url):]).group(1)))
    return title, units


async def print_unit(context, sem, url, pdf_path, md_path):
    async with sem:
        page = await context.new_page()
        try:
            for attempt in range(3):  # retry slow pages instead of failing
                try:
                    await page.goto(url, wait_until="load", timeout=60000)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    print(f"    retry {attempt + 1} for {url}")
            try:  # wait for late content, but don't fail on a page that keeps a connection open
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await page.add_style_tag(content=HIDE_CSS)
            await page.evaluate(REMOVE_NEXT_UNIT_JS)
            await page.emulate_media(media="print")
            title = re.sub(r"\s*-\s*Training.*$", "", await page.title())
            await page.pdf(path=str(pdf_path), format="A4", print_background=True,
                           margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"})
            meta = PdfWriter(clone_from=str(pdf_path))
            meta.add_metadata({"/Title": title, "/Subject": url})
            meta.write(str(pdf_path))
            if md_path:
                try:
                    req = urllib.request.Request(url + "?accept=text/markdown",
                                                 headers={"User-Agent": "Mozilla/5.0"})
                    md_path.write_bytes(urllib.request.urlopen(req, timeout=30).read())
                except Exception as e:
                    print(f"    (no markdown for {url}: {e})")
            print(f"    ok  {pdf_path.name}")
            return title
        finally:
            await page.close()


async def main():
    ap = argparse.ArgumentParser(description="Microsoft Learn -> PDF")
    ap.add_argument("urls", nargs="+", help="certification, course, learning path or module URL(s)")
    ap.add_argument("-o", "--out", default="learn-pdf", help="output folder (default: learn-pdf)")
    ap.add_argument("--dry-run", action="store_true", help="only list modules and units")
    ap.add_argument("--markdown", action="store_true", help="also save units as Markdown")
    ap.add_argument("--parallel", type=int, default=4, help="pages printed at once (default 4)")
    ap.add_argument("--per-unit", action="store_true",
                    help="one PDF per unit/chapter, all in the output folder (no module PDFs)")
    ap.add_argument("--keep-units", action="store_true", help="keep the separate per-unit files")
    ap.add_argument("--combined", action="store_true", help="also make one big PDF of everything")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)  # page.pdf() needs headless Chromium
        context = await browser.new_context(locale="en-US")
        page = await context.new_page()

        print("Finding modules...")
        modules = []
        for u in args.urls:
            modules += await find_modules(page, u)
        modules = uniq(modules)
        if not modules:
            sys.exit("No modules found. Try passing the learning path URLs directly.")

        plan = []
        for i, m in enumerate(modules, 1):
            title, units = await find_units(page, m)
            print(f"[{i:02d}] {title}  ({len(units)} units)")
            plan.append((i, m, title, units))
        await page.close()
        total = sum(len(p[3]) for p in plan)
        print(f"\n{len(plan)} modules, {total} units.")
        if args.dry_run:
            await browser.close()
            return

        sem = asyncio.Semaphore(args.parallel)

        if args.per_unit:
            # flat folder: 01-03-analyze-zero-trust-security-model.pdf (module-unit-name)
            for i, m, title, units in plan:
                print(f"\n[{i:02d}] {title}")
                pdfs = [out / f"{i:02d}-{j:02d}-{safe(u.rstrip('/').split('/')[-1])}.pdf"
                        for j, u in enumerate(units, 1)]
                results = await asyncio.gather(
                    *[print_unit(context, sem, u, p,
                                 p.with_suffix(".md") if args.markdown else None)
                      for u, p in zip(units, pdfs)],
                    return_exceptions=True)
                for p, r in zip(pdfs, results):
                    if isinstance(r, Exception):
                        print(f"    FAILED {p.name}: {r}")
            await browser.close()
            print(f"\nDone. One PDF per unit in: {out.resolve()}")
            return

        book = PdfWriter() if args.combined else None
        work = out / "_units"  # temporary per-unit files
        for i, m, title, units in plan:
            base = f"{i:02d}-{safe(title)}"
            mdir = work / base
            mdir.mkdir(parents=True, exist_ok=True)
            print(f"\n[{i:02d}] {title}")
            pdfs = [mdir / f"{j:02d}-{safe(u.rstrip('/').split('/')[-1])}.pdf"
                    for j, u in enumerate(units, 1)]
            tasks = [print_unit(context, sem, u, p,
                                p.with_suffix(".md") if args.markdown else None)
                     for u, p in zip(units, pdfs)]
            titles = await asyncio.gather(*tasks, return_exceptions=True)

            # one PDF per module, with a bookmark per unit and the module title as metadata
            module_pdf = PdfWriter()
            md_parts = [f"# {title}\n\nSource: {m}\n"]
            parent = None
            for p, t in zip(pdfs, titles):
                if isinstance(t, Exception) or not p.exists():
                    print(f"    FAILED {p.name}: {t}")
                    continue
                module_pdf.append(str(p), outline_item=t)
                md = p.with_suffix(".md")
                if md.exists():
                    md_parts.append(md.read_text(encoding="utf-8", errors="replace"))
                if book is not None:
                    start = len(book.pages)
                    book.append(str(p))
                    if parent is None:
                        parent = book.add_outline_item(title, start)
                    book.add_outline_item(t, start, parent=parent)
            module_pdf.add_metadata({"/Title": title, "/Subject": m})
            module_pdf.write(out / f"{base}.pdf")
            if args.markdown and len(md_parts) > 1:
                (out / f"{base}.md").write_text("\n\n---\n\n".join(md_parts), encoding="utf-8")
            print(f"  -> {base}.pdf")

        if book is not None:
            book.write(out / f"{safe(out.name)}-complete.pdf")
        if not args.keep_units:
            shutil.rmtree(work, ignore_errors=True)
        await browser.close()
    print(f"\nDone. One PDF per module in: {out.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
