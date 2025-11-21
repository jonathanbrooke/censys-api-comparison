# Censys API Comparison Tool

A web-based tool to compare search results between Censys Legacy API (v2) and New Platform API (v3).

## API Endpoints

This tool queries the following Censys API endpoints:

- **Legacy API (v2)**: `GET https://search.censys.io/api/v2/hosts/search`
  - Authentication: HTTP Basic Auth (API ID + Secret)
  - Returns host search results with IP addresses
  - Supports virtual hosts filtering

- **New Platform API (v3)**: `POST https://api.platform.censys.io/v3/global/search/query`
  - Authentication: Bearer token + `X-Organization-ID` header
  - Returns unified search results across multiple resource types
  - Includes web properties and host data

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
