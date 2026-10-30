"""Offline tests for trades.py: Dhan-style tradebooks in, ICT-tagged round trips and rule replay out."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("trades", os.path.join(ROOT, "ict-india", "trades.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_mmxm as M  # noqa: E402

HEADER = ["Date", "Time", "Name", "Buy/Sell", "Order Type", "Quantity", "Trade Price", "Trade Value", "Exchange"]
ROWS = [
    # Tue 9 Sep 2025, BANKNIFTY 30 Sep 54000 PE bought in the AM killzone: +2,662.50 in 6 minutes
    ["09-09-2025", "09:41:05", "BANKNIFTY 30 SEP 54000 PUT", "BUY", "MARKET", "105", "210.50", "", "NSE"],
    ["09-09-2025", "09:44:00", "BANKNIFTY 30 SEP 54000 PUT", "SELL", "LIMIT", "60", "238.00", "", "NSE"],
    ["09-09-2025", "09:47:10", "BANKNIFTY 30 SEP 54000 PUT", "SELL", "LIMIT", "45", "233.00", "", "NSE"],
    # same day, opening-range call bought and lost: -1,575
    ["09-09-2025", "09:18:00", "NIFTY 09 SEP 25000 CALL", "BUY", "MARKET", "75", "101.00", "", "NSE"],
    ["09-09-2025", "09:21:30", "NIFTY 09 SEP 25000 CALL", "SELL", "MARKET", "75", "80.00", "", "NSE"],
    # Fri 12 Sep 2025, PM killzone, sold a call (short the index) and bought it back: +1,500
    ["12-09-2025", "13:30:00", "NIFTY 16 SEP 25300 CALL", "SELL", "LIMIT", "150", "50.00", "", "NSE"],
    ["12-09-2025", "13:52:00", "NIFTY 16 SEP 25300 CALL", "BUY", "LIMIT", "150", "40.00", "", "NSE"],
]


def write_csv(path, rows):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Tradebook", "Client: XXXX"])      # broker preamble before the real header
        w.writerow([])
        w.writerow(HEADER)
        w.writerows(rows)


def write_xlsx(path, rows):
    """A minimal xlsx with inline strings, like many broker exports."""
    def cell(ref, v):
        return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, v)
    xml_rows = []
    for i, r in enumerate([HEADER] + rows, start=1):
        xml_rows.append('<row r="%d">%s</row>' % (i, "".join(cell("%s%d" % (chr(65 + k), i), v) for k, v in enumerate(r))))
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>%s</sheetData></worksheet>' % "".join(xml_rows))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)


NOTE_LINES = [
    "CONTRACT NOTE CUM TAX INVOICE",
    "Trade Date: 09/09/2025          Settlement No: 2025171",
    "Order No.          Order Time  Trade No.   Trade Time  Security / Contract Description          B/S   Quantity   Gross Rate   Net Total",
    "1100000012345678   09:41:02    50012345    09:41:05    OPTIDX BANKNIFTY 30SEP2025 54000.00 PE    B     105        210.50       -22102.50",
    "1100000012345679   09:43:58    50012399    09:44:00    OPTIDX BANKNIFTY 30SEP2025 54000.00 PE    S     60         238.00       14280.00",
    "1100000012345680   09:47:08    50012411    09:47:10    OPTIDX BANKNIFTY 30SEP2025 54000.00 PE    S     45         233.00       10485.00",
    "1100000012345690   09:50:00    ADJUSTMENT NIFTY ROUNDING",
    "Total                                                                                                   2662.50",
]


def make_pdf(path, lines, password=None):
    """A one-page PDF in Courier with one text line per row, optionally locked like a broker contract note."""
    esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 7 Tf 10 800 Td 10 TL " + " ".join("(%s) Tj T*" % esc(l) for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1000 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            "<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    out, offs = "%PDF-1.4\n", []
    for k, o in enumerate(objs, 1):
        offs.append(len(out))
        out += "%d 0 obj\n%s\nendobj\n" % (k, o)
    xref = len(out)
    out += "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + "".join("%010d 00000 n \n" % x for x in offs)
    out += "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "w", encoding="latin-1") as f:
        f.write(out)
    if password:
        import pypdf
        w = pypdf.PdfWriter(clone_from=pypdf.PdfReader(path))
        w.encrypt(password)
        with open(path, "wb") as f:
            w.write(f)


def have_pdf_tools():
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


class TestTrades(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        T.mmxm.STATE_DIR = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_contract_parsing(self):
        d = date(2025, 9, 9)
        c = T.parse_contract("BANKNIFTY 30 SEP 54000 PUT", d)
        self.assertEqual((c["underlying"], c["kind"], c["strike"], c["expiry"]), ("BANKNIFTY", "PE", 54000.0, date(2025, 9, 30)))
        c = T.parse_contract("NIFTY-25-Sep-2025-25000-CE", d)
        self.assertEqual((c["underlying"], c["kind"], c["expiry"]), ("NIFTY", "CE", date(2025, 9, 25)))
        c = T.parse_contract("NIFTY25O0725000CE", d)                     # NSE weekly code: 7 Oct 2025
        self.assertEqual((c["underlying"], c["expiry"]), ("NIFTY", date(2025, 10, 7)))
        self.assertEqual(T.parse_contract("BANKNIFTY SEP FUT", d)["kind"], "FUT")

    def test_round_trips_and_tags(self):
        p = os.path.join(self.tmp, "tb.csv")
        write_csv(p, ROWS)
        rep, trips = T.build([p])
        self.assertEqual(rep["overall"]["trades"], 3)
        self.assertEqual(rep["overall"]["pnl"], 2662.5 - 1575.0 + 1500.0)
        bn = next(t for t in trips if t["underlying"] == "BANKNIFTY")
        self.assertEqual((bn["pnl"], bn["view"], bn["window"], bn["hold_min"], bn["dte"]), (2662.5, "short", "am", 6.1, 21))
        nf = next(t for t in trips if t["symbol"].startswith("NIFTY 09"))
        self.assertEqual((nf["window"], nf["expiry_day"], nf["nth_today"]), ("opening_range", True, 1))
        sc = next(t for t in trips if t["style"] == "sell CE")
        self.assertEqual((sc["view"], sc["window"], sc["weekday"], sc["pnl"]), ("short", "pm", "Fri", 1500.0))

    def test_rule_replay(self):
        p = os.path.join(self.tmp, "tb.csv")
        write_csv(p, ROWS)
        rep, _ = T.build([p])
        rules = {r["rule"]: r for r in rep["rules"]}
        self.assertEqual(rules["No trades in the 09:15-09:30 opening range"]["blocked_pnl"], -1575.0)   # saved you 1,575
        self.assertEqual(rules["No new positions on Friday"]["blocked_pnl"], 1500.0)                   # cost you 1,500
        self.assertEqual(rules["All of the above together"]["blocked"], 2)

    def test_xlsx_and_duplicates(self):
        a, b = os.path.join(self.tmp, "a.xlsx"), os.path.join(self.tmp, "b.csv")
        write_xlsx(a, ROWS)
        write_csv(b, ROWS[:3])                                           # overlapping export
        rep, _ = T.build([a, b])
        self.assertEqual(rep["fills"], len(ROWS))
        self.assertEqual(rep["overall"]["pnl"], 2587.5)

    def test_month_filter(self):
        p = os.path.join(self.tmp, "tb.csv")
        write_csv(p, ROWS + [["15-07-2025", "10:00:00", "NIFTY 17 JUL 25000 CALL", "BUY", "M", "75", "100", "", "NSE"],
                             ["15-07-2025", "10:05:00", "NIFTY 17 JUL 25000 CALL", "SELL", "M", "75", "90", "", "NSE"]])
        rep, _ = T.build([p], months={"2025-09"})
        self.assertEqual(rep["overall"]["trades"], 3)

    def test_excel_serial_dates(self):
        self.assertEqual(T.parse_dt("45909", "0.4034722"), datetime(2025, 9, 9, 9, 41))
        self.assertEqual(T.parse_dt("45909.4034722"), datetime(2025, 9, 9, 9, 41))
        self.assertEqual(T.parse_dt("09 Sep 2025", "09:41:05 AM"), datetime(2025, 9, 9, 9, 41, 5))

    @unittest.skipUnless(have_pdf_tools(), "needs pypdf to build a locked PDF")
    def test_locked_contract_notes_in_a_zip(self):
        pdf = os.path.join(self.tmp, "cn-09-09-2025.pdf")
        make_pdf(pdf, NOTE_LINES, password="ABCDE1234F")
        with self.assertRaises(ValueError) as e:
            T.build([pdf])
        self.assertIn("password", str(e.exception))
        z = os.path.join(self.tmp, "notes.zip")
        with zipfile.ZipFile(z, "w") as zz:
            zz.write(pdf, "Sep/cn-09-09-2025.pdf")
            zz.writestr("readme.txt", "ignored")
        rep, trips = T.build([z], password="ABCDE1234F")
        self.assertEqual(rep["fills"], 3)
        self.assertEqual(len(trips), 1)
        t = trips[0]
        self.assertEqual((t["underlying"], t["kind"], t["expiry"], t["pnl"], t["window"]),
                         ("BANKNIFTY", "PE", date(2025, 9, 30), 2662.5, "am"))
        self.assertEqual(t["entry_t"], datetime(2025, 9, 9, 9, 41, 5))   # trade time, not order time
        self.assertEqual(len(rep["unparsed"]), 1)                         # the adjustment line is reported, not guessed

    @unittest.skipUnless(have_pdf_tools(), "needs pypdf to build a PDF")
    def test_contract_note_and_tradebook_together(self):
        pdf = os.path.join(self.tmp, "cn.pdf")
        make_pdf(pdf, NOTE_LINES)
        csvp = os.path.join(self.tmp, "tb.csv")
        write_csv(csvp, ROWS[3:])
        rep, _ = T.build([pdf, csvp])
        self.assertEqual(rep["overall"]["trades"], 3)
        self.assertEqual(rep["overall"]["pnl"], 2587.5)

    def test_ict_context_against_index_bars(self):
        # the textbook India session from test_mmxm: short filled at 10:35 IST on 20 Oct 2026
        bars = M.india_bars(M.IN, M.IN_P)
        bp = os.path.join(self.tmp, "bars.csv")
        with open(bp, "w") as f:
            f.write("time,open,high,low,close\n")
            for b in bars:
                f.write("%d,%s,%s,%s,%s\n" % (b.t, b.o, b.h, b.l, b.c))
        p = os.path.join(self.tmp, "tb.csv")
        write_csv(p, [["20-10-2026", "10:36:00", "BANKNIFTY 28 OCT 56000 PUT", "BUY", "M", "30", "200", "", "NSE"],
                      ["20-10-2026", "10:52:00", "BANKNIFTY 28 OCT 56000 PUT", "SELL", "M", "30", "260", "", "NSE"],
                      ["20-10-2026", "13:20:00", "BANKNIFTY 28 OCT 56000 CALL", "BUY", "M", "30", "150", "", "NSE"],
                      ["20-10-2026", "13:30:00", "BANKNIFTY 28 OCT 56000 CALL", "SELL", "M", "30", "140", "", "NSE"]])
        rep, trips = T.build([p], bars=bp)
        put, call = trips
        self.assertTrue(put["after_sweep"] and put["mmxm_live"])
        self.assertFalse(call["mmxm_live"])
        self.assertEqual(rep["ict"]["checked"], 2)


if __name__ == "__main__":
    unittest.main()
