import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

app = Flask(__name__)

LEGACY_API_ID = os.getenv("CENSYS_LEGACY_API_ID")
LEGACY_API_SECRET = os.getenv("CENSYS_LEGACY_API_SECRET")
NEW_API_KEY = os.getenv("CENSYS_NEW_API_KEY")
ORG_ID = os.getenv("CENSYS_ORG_ID")

LEGACY_URL = "https://search.censys.io/api/v2/hosts/search"
NEW_URL = "https://api.platform.censys.io/v3/global/search/query"

# Database setup
DB_FILE = "censys_searches.db"


def init_db():
    """Initialize the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            legacy_query TEXT NOT NULL,
            new_query TEXT NOT NULL,
            results TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# Initialize database on startup
init_db()


def strip_quotes(text):
    """
    Remove surrounding double quotes from a string if present.
    """
    text = text.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1]
    return text


def get_legacy_results(query, limit=100, virtual_hosts="EXCLUDE"):
    """Fetch results from Legacy Censys API."""
    ips = set()
    total_hits = 0
    error = None

    auth = (LEGACY_API_ID, LEGACY_API_SECRET)
    params = {
        "q": query,
        "per_page": limit,
        "virtual_hosts": virtual_hosts,
        "fields": ["ip"]
    }

    try:
        response = requests.get(LEGACY_URL, auth=auth, params=params)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", {})
        total_hits = result.get("total", 0)
        hits = result.get("hits", [])

        for hit in hits:
            if "ip" in hit:
                ips.add(hit["ip"])

    except requests.exceptions.RequestException as e:
        error = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error += f" - {e.response.text}"

    return ips, total_hits, error


def get_new_results(query, limit=100):
    """Fetch results from New Censys Platform API."""
    ips = set()
    total_hits = 0
    error = None

    headers = {
        "Authorization": f"Bearer {NEW_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    if ORG_ID:
        headers["X-Organization-ID"] = ORG_ID

    payload = {
        "query": query,
        "page_size": limit
    }

    try:
        response = requests.post(NEW_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", {})
        # New API v3 doesn't return 'total' in the same way
        hits = result.get("hits", [])
        total_hits = result.get("total_results",
                                result.get("total_count",
                                           result.get("total", len(hits))))

        for hit in hits:
            # Try webproperty_v1 structure
            if 'webproperty_v1' in hit:
                resource = hit['webproperty_v1'].get('resource', {})
                if 'hostname' in resource:
                    hostname = resource['hostname']
                    if hostname.replace('.', '').isdigit():
                        ips.add(hostname)
                endpoints = resource.get('endpoints', [])
                for endpoint in endpoints:
                    if 'ip' in endpoint:
                        ips.add(endpoint['ip'])

            # Try host_v1 structure
            elif 'host_v1' in hit:
                resource = hit['host_v1'].get('resource', {})
                if 'ip' in resource:
                    ips.add(resource['ip'])

            # Fallback: direct keys
            elif "ip" in hit:
                ips.add(hit["ip"])
            elif "ip_address" in hit:
                ips.add(hit["ip_address"])

    except requests.exceptions.RequestException as e:
        error = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error += f" - {e.response.text}"

    return ips, total_hits, error


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/compare', methods=['POST'])
def compare():
    """Compare queries between Legacy and New APIs."""
    data = request.get_json()
    legacy_query = strip_quotes(data.get('legacy_query', ''))
    new_query = strip_quotes(data.get('new_query', ''))
    virtual_hosts = data.get('virtual_hosts', 'EXCLUDE')

    if not legacy_query or not new_query:
        return jsonify({
            'error': 'Both queries are required'
        }), 400

    # Fetch results from both APIs
    legacy_ips, legacy_total, legacy_error = get_legacy_results(
        legacy_query, virtual_hosts=virtual_hosts
    )
    new_ips, new_total, new_error = get_new_results(new_query)

    # Calculate differences
    missing_in_new = legacy_ips - new_ips
    only_in_new = new_ips - legacy_ips
    common_ips = legacy_ips & new_ips

    # Determine status
    if legacy_error or new_error:
        status = 'error'
    elif missing_in_new:
        status = 'warning'
    else:
        status = 'success'

    return jsonify({
        'status': status,
        'legacy': {
            'total': legacy_total,
            'fetched': len(legacy_ips),
            'ips': sorted(list(legacy_ips)),
            'error': legacy_error
        },
        'new': {
            'total': new_total,
            'fetched': len(new_ips),
            'ips': sorted(list(new_ips)),
            'error': new_error
        },
        'comparison': {
            'common': len(common_ips),
            'missing_in_new': sorted(list(missing_in_new)),
            'only_in_new': sorted(list(only_in_new))
        }
    })


@app.route('/save-search', methods=['POST'])
def save_search():
    """Save a search to the database."""
    data = request.get_json()
    name = data.get('name', '').strip()
    legacy_query = data.get('legacy_query', '')
    new_query = data.get('new_query', '')
    results = data.get('results', {})

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO saved_searches (name, legacy_query, new_query, results) '
        'VALUES (?, ?, ?, ?)',
        (name, legacy_query, new_query, json.dumps(results))
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Search saved successfully'})


@app.route('/load-searches', methods=['GET'])
def load_searches():
    """Load all saved searches from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, name, legacy_query, new_query, results, timestamp '
        'FROM saved_searches ORDER BY timestamp DESC'
    )
    rows = cursor.fetchall()
    conn.close()

    searches = []
    for row in rows:
        searches.append({
            'id': row[0],
            'name': row[1],
            'legacy_query': row[2],
            'new_query': row[3],
            'results': json.loads(row[4]),
            'timestamp': row[5]
        })

    return jsonify(searches)


@app.route('/delete-search/<int:search_id>', methods=['DELETE'])
def delete_search(search_id):
    """Delete a saved search from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM saved_searches WHERE id = ?', (search_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Search deleted successfully'})


if __name__ == '__main__':
    if not all([LEGACY_API_ID, LEGACY_API_SECRET, NEW_API_KEY]):
        print("Error: Missing API credentials in .env file.")
        exit(1)
    
    print("Starting Censys API Comparison Web App...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)
