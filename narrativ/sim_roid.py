"""Probe (owner, 24 Nov 2026): what is inside NSE's structured 'Resignation of Director/KMP/SMP' (ROID) and
'Resignation of Statutory Auditor' (ROSA) attachments? Prints the file list and the start of each file. Changes nothing.
python -m narrativ.sim_roid"""
import io
import zipfile
from pathlib import Path

from narrativ.filings import NSESession

URLS = ["https://nsearchives.nseindia.com/corporate/LUMAXTECH_ROID_99016_KMP_Doc.zip",
        "https://nsearchives.nseindia.com/corporate/IPL_ROID_89673_KMP_Doc.zip",
        "https://nsearchives.nseindia.com/corporate/TMCV_ROSA_102750_KMP_Doc.zip"]


def main() -> None:
    ns, out = NSESession(), []
    print = out.append  # noqa: A001 (public logs are quiet: write the result to docs/research/sim_roid.md)
    for u in URLS:
        try:
            r = ns.s.get(u, timeout=60)
            print(f"== {u} {r.status_code} {len(r.content)} bytes {r.content[:4]!r}")
            z = zipfile.ZipFile(io.BytesIO(r.content))
            for n in z.namelist():
                b = z.read(n)
                print(f"-- {n} ({len(b)} bytes)")
                if n.lower().endswith(".xml"):
                    import re
                    for tag, val in re.findall(r"<in-capmkt(?:-ent)?:(\w+)[^>]*>([^<]{1,200})</", b.decode("utf-8", "replace")):
                        print(f"   {tag} = {val.strip()}")
                elif n.lower().endswith(".pdf") and False:
                    from pypdf import PdfReader
                    print((PdfReader(io.BytesIO(b)).pages[0].extract_text() or "")[:1500])
        except Exception as e:  # noqa: BLE001
            print(f"!! {u}: {type(e).__name__}: {e}")
    Path("docs/research/sim_roid.md").write_text("```\n" + "\n".join(str(x) for x in out) + "\n```\n")


if __name__ == "__main__":
    main()
