import os
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
import pypdf

app = Flask(__name__)
CORS(app)

# Money values like 0.00, 2,000.00, 137,400.00 (works even if two are glued together)
NUM_RE = re.compile(r'\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}')
STREAM_RE = re.compile(r'Fee Balances.*\)\s*-\s*(.*)', re.IGNORECASE)
TOTAL_DUE_RE = re.compile(r'Total Balance Due:\s*(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})', re.IGNORECASE)


def to_float(s):
    return float(s.replace(',', ''))


def split_row_and_adm(head, expected_row):
    """
    head is everything before the 5 money columns, e.g.
      '1 6451 MILLICENT NTINYARI'   (row number and adm separated)
      '10 6522 HILDA KAWIRA KOBIA'  (separated)
      '106522 HILDA KAWIRA KOBIA'   (row number glued onto adm by the PDF reader)
    Returns (adm, name) or None.
    """
    # Normal case: "<row> <adm> <name>"
    m = re.match(r'^(\d+)\s+(\d+)\s+(.+)$', head)
    if m:
        return m.group(2), m.group(3).strip()

    # Glued case: "<row><adm> <name>"
    m = re.match(r'^(\d{3,})\s+(.+)$', head)
    if m:
        s, name = m.group(1), m.group(2).strip()
        row_str = str(expected_row)
        if s.startswith(row_str) and len(s) - len(row_str) >= 3:
            return s[len(row_str):], name
        # Fallback on length: 2-digit row + 4-digit adm, else 1-digit row
        if len(s) >= 6:
            return s[2:], name
        return s[1:], name

    return None


def parse_text(text):
    students = []
    totals = {}          # stream -> "Total Balance Due" printed in the PDF
    current_stream = "Unknown"
    expected_row = 1

    for raw in text.split('\n'):
        line = raw.replace('|', ' ').strip()
        if not line:
            continue

        # Stream / class header
        m = STREAM_RE.search(line)
        if m:
            current_stream = m.group(1).strip()
            expected_row = 1
            continue

        # Class total printed at the bottom of each page
        t = TOTAL_DUE_RE.search(line)
        if t:
            totals[current_stream] = to_float(t.group(1))
            continue

        # Student rows start with a digit and end with 5 money columns
        if not line[0].isdigit():
            continue
        nums = list(NUM_RE.finditer(line))
        if len(nums) < 5:
            continue
        last5 = nums[-5:]
        head = line[:last5[0].start()].strip()
        parsed = split_row_and_adm(head, expected_row)
        if not parsed:
            continue
        adm, name = parsed
        name = re.sub(r'\s+', ' ', name)
        balance = last5[-1].group(0)

        students.append({
            'adm': adm,
            'name': name,
            'stream': current_stream,
            'balance': balance,
        })
        expected_row += 1

    return students, totals


def build_checks(students, totals):
    sums, counts = {}, {}
    for s in students:
        sums[s['stream']] = round(sums.get(s['stream'], 0) + to_float(s['balance']), 2)
        counts[s['stream']] = counts.get(s['stream'], 0) + 1

    checks = []
    for stream, expected in totals.items():
        got = sums.get(stream, 0.0)
        checks.append({
            'stream': stream,
            'count': counts.get(stream, 0),
            'sum': got,
            'expected': expected,
            'ok': abs(got - expected) < 0.01,
        })
    return checks


def read_text(reader, layout):
    parts = []
    for page in reader.pages:
        try:
            if layout:
                parts.append(page.extract_text(extraction_mode="layout") or "")
            else:
                parts.append(page.extract_text() or "")
        except TypeError:
            return None  # older pypdf without layout mode
    return "\n".join(parts)


@app.route('/extract', methods=['POST'])
def extract_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    try:
        reader = pypdf.PdfReader(request.files['file'])
    except Exception as e:
        return jsonify({"error": f"Could not read PDF: {e}"}), 400

    best = None
    for layout in (False, True):
        text = read_text(reader, layout)
        if not text:
            continue
        students, totals = parse_text(text)
        checks = build_checks(students, totals)
        ok_count = sum(1 for c in checks if c['ok'])
        score = (ok_count, len(students))
        if best is None or score > best[0]:
            best = (score, students, checks)

    if best is None:
        return jsonify({"students": [], "warnings": [], "checks": []})

    _, students, checks = best
    warnings = [
        f"{c['stream']}: got {c['count']} students, balance {c['sum']:,.2f} "
        f"but PDF says {c['expected']:,.2f}"
        for c in checks if not c['ok']
    ]

    return jsonify({"students": students, "warnings": warnings, "checks": checks})


@app.route('/', methods=['GET'])
def health():
    return "pdfslip api ok"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
