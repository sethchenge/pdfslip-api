from flask import Flask, request, jsonify
from flask_cors import CORS
import pypdf
import re
import os

app = Flask(__name__)
CORS(app)

@app.route('/extract', methods=['POST'])
def extract_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    reader = pypdf.PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
        
    students = []
    current_stream = "Unknown"
    
    for line in text.split('\n'):
        line = line.replace('|', '').strip()
        
        m = re.search(r'Fee Balances.*\)\s*-\s*(.*)', line, re.IGNORECASE)
        if m:
            current_stream = m.group(1).strip()
            continue
            
        row_match = re.match(r'^(\d+)\s+(\d+)\s+(.+?)\s+([\d,.]+(?:\s+[\d,.]+){3,})$', line)
        if row_match:
            students.append({
                'adm': row_match.group(2).strip(),
                'name': row_match.group(3).strip(),
                'stream': current_stream,
                'balance': row_match.group(4).strip().split()[-1]
            })
            
    return jsonify({"students": students})

if __name__ == '__main__':
    # Cloud hosts use the PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
