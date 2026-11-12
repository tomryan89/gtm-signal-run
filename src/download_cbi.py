"""Download the Central Bank of Ireland registers listed in settings.toml (PDF only) and convert to text."""
import html
import re
import subprocess
import time

import requests

from common import RAW, log, settings

URL = "https://registers.centralbank.ie/DownloadsPage.aspx"
OUT = RAW / "cbi"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


def main():
    wanted = settings()["universe"]["cbi_registers"]
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (gtm-signals research script)"
    page = s.get(URL, timeout=60).text
    # each register link: __doPostBack('target','') followed by a span with its label
    links = re.findall(r"__doPostBack\('([^']+)',''\)\"><span[^>]*>([^<]+)</span>", page)
    links = [(t, html.unescape(lbl).strip()) for t, lbl in links]
    for prefix in wanted:
        match = [(t, lbl) for t, lbl in links if lbl.startswith(prefix)]
        if len(match) != 1:
            print(f"!! {prefix}: {len(match)} matches")
            log("cbi", "label_mismatch", register=prefix, matches=len(match))
            continue
        target, label = match[0]
        pdf = OUT / f"{slug(prefix)}.pdf"
        if not pdf.exists():
            form = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))
            form.update(__EVENTTARGET=target, __EVENTARGUMENT="")
            t0 = time.time()
            r = s.post(URL, data=form, timeout=120)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("application/pdf"):
                raise RuntimeError(f"{prefix}: not a PDF")
            pdf.write_bytes(r.content)
            log("cbi", "download", register=label, bytes=len(r.content), secs=round(time.time() - t0, 1))
            time.sleep(2)
        subprocess.run(["pdftotext", "-layout", str(pdf), str(pdf.with_suffix(".txt"))], check=True)
        (OUT / f"{slug(prefix)}.label").write_text(label)
        print("ok", label)


if __name__ == "__main__":
    main()
