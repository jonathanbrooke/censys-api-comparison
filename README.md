# Censys API Comparison Tool

A web-based tool to compare search results between Censys Legacy API (v2) and New Platform API (v3).

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   - Copy `example.env` to `.env`
   - Fill in your Censys API credentials:
     ```
     CENSYS_LEGACY_API_ID=your_legacy_api_id
     CENSYS_LEGACY_API_SECRET=your_legacy_api_secret
     CENSYS_NEW_API_KEY=your_new_api_key
     CENSYS_ORG_ID=your_org_id
     ```

3. **Start the application:**
   ```bash
   python app.py
   ```

4. **Open in browser:**
   - Navigate to `http://localhost:5000`

## Features

- Compare query results between Legacy and New Censys APIs
- Save searches to local database for later review
- Filter and sort saved searches
- View detailed IP comparisons and differences
