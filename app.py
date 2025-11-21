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
            virtual_hosts TEXT DEFAULT 'INCLUDE',
            results TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Add virtual_hosts column to existing tables if it doesn't exist
    cursor.execute("PRAGMA table_info(saved_searches)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'virtual_hosts' not in columns:
        cursor.execute(
            'ALTER TABLE saved_searches ADD COLUMN '
            'virtual_hosts TEXT DEFAULT "INCLUDE"'
        )
    conn.commit()
    conn.close()


# Initialize database on startup
init_db()


def get_legacy_results(query, limit=100, virtual_hosts="INCLUDE",
                       fetch_all=False):
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
        # Fetch first page
        response = requests.get(LEGACY_URL, auth=auth, params=params)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", {})
        total_hits = result.get("total", 0)
        hits = result.get("hits", [])

        for hit in hits:
            if "ip" in hit:
                ips.add(hit["ip"])

        # Paginate if fetch_all is enabled
        if fetch_all:
            next_cursor = result.get("links", {}).get("next")
            while next_cursor:
                try:
                    response = requests.get(
                        next_cursor,
                        auth=auth,
                        timeout=30
                    )
                    response.raise_for_status()
                    data = response.json()
                    result = data.get("result", {})
                    hits = result.get("hits", [])
                    
                    for hit in hits:
                        if "ip" in hit:
                            ips.add(hit["ip"])
                    
                    next_cursor = result.get("links", {}).get("next")
                except Exception as e:
                    error = f"Pagination error: {str(e)}"
                    break

    except requests.exceptions.RequestException as e:
        error = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error += f" - {e.response.text}"

    return ips, total_hits, error


def get_new_results(query, limit=100, fetch_all=False):
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

    def extract_ips_from_hits(hits):
        """Helper to extract IPs from hit results."""
        extracted = set()
        for hit in hits:
            # Try webproperty_v1 structure
            if 'webproperty_v1' in hit:
                resource = hit['webproperty_v1'].get('resource', {})
                if 'hostname' in resource:
                    hostname = resource['hostname']
                    if hostname.replace('.', '').isdigit():
                        extracted.add(hostname)
                endpoints = resource.get('endpoints', [])
                for endpoint in endpoints:
                    if 'ip' in endpoint:
                        extracted.add(endpoint['ip'])

            # Try host_v1 structure
            elif 'host_v1' in hit:
                resource = hit['host_v1'].get('resource', {})
                if 'ip' in resource:
                    extracted.add(resource['ip'])

            # Fallback: direct keys
            elif "ip" in hit:
                extracted.add(hit["ip"])
            elif "ip_address" in hit:
                extracted.add(hit["ip_address"])
        return extracted

    try:
        # Fetch first page
        response = requests.post(NEW_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", {})
        hits = result.get("hits", [])
        total_hits = result.get("total_results",
                                result.get("total_count",
                                           result.get("total", len(hits))))

        ips.update(extract_ips_from_hits(hits))

        # Paginate if fetch_all is enabled
        if fetch_all:
            page_token = result.get("links", {}).get("next")
            while page_token:
                try:
                    payload["cursor"] = page_token
                    response = requests.post(
                        NEW_URL,
                        headers=headers,
                        json=payload,
                        timeout=30
                    )
                    response.raise_for_status()
                    data = response.json()
                    result = data.get("result", {})
                    hits = result.get("hits", [])

                    ips.update(extract_ips_from_hits(hits))

                    page_token = result.get("links", {}).get("next")
                except Exception as e:
                    error = f"Pagination error: {str(e)}"
                    break

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
    legacy_query = data.get('legacy_query', '').strip()
    new_query = data.get('new_query', '').strip()
    virtual_hosts = data.get('virtual_hosts', 'EXCLUDE')
    fetch_all = data.get('fetch_all', False)

    if not legacy_query or not new_query:
        return jsonify({
            'error': 'Both queries are required'
        }), 400

    # Fetch results from both APIs
    legacy_ips, legacy_total, legacy_error = get_legacy_results(
        legacy_query, virtual_hosts=virtual_hosts, fetch_all=fetch_all
    )
    new_ips, new_total, new_error = get_new_results(
        new_query, fetch_all=fetch_all
    )

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
    virtual_hosts = data.get('virtual_hosts', 'INCLUDE')
    results = data.get('results', {})
    overwrite = data.get('overwrite', False)

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Check if name already exists
    cursor.execute('SELECT id FROM saved_searches WHERE name = ?', (name,))
    existing = cursor.fetchone()

    if existing and not overwrite:
        conn.close()
        return jsonify({
            'duplicate': True,
            'message': 'A search with this name already exists'
        }), 409

    if existing and overwrite:
        # Update existing entry
        cursor.execute(
            'UPDATE saved_searches SET legacy_query = ?, new_query = ?, '
            'virtual_hosts = ?, results = ?, timestamp = CURRENT_TIMESTAMP '
            'WHERE name = ?',
            (legacy_query, new_query, virtual_hosts,
             json.dumps(results), name)
        )
    else:
        # Insert new entry
        cursor.execute(
            'INSERT INTO saved_searches '
            '(name, legacy_query, new_query, virtual_hosts, results) '
            'VALUES (?, ?, ?, ?, ?)',
            (name, legacy_query, new_query, virtual_hosts,
             json.dumps(results))
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
        'SELECT id, name, legacy_query, new_query, virtual_hosts, '
        'results, timestamp FROM saved_searches ORDER BY timestamp DESC'
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
            'virtual_hosts': row[4],
            'results': json.loads(row[5]),
            'timestamp': row[6]
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
