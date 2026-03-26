# SEngine

SEngine is a fast, lightweight search engine with a built-in multithreaded web crawler and a Flask-based web interface. 

## Features
- **Multithreaded Web Crawler:** Quickly scrape webpages, extracting text, links, images, videos, lists, and tables to store in an SQLite database.
- **Search Interface:** A beautiful, responsive web interface to query the indexed data.
- **Search Categories:** Dedicated search tabs for **Web**, **Images**, and **Videos**.
- **Safe Search:** Built-in robust filtering for NSFW content, configurable in the Settings.
- **Smart Intents:**
  - **Calculator:** Instantly evaluate math expressions directly from the search bar (e.g., `5 * (10 + 2)`).
  - **Timer:** Instantly start countdowns (e.g., `10 min timer` or `45 sec`).
  - **Infoboxes:** Displays dynamic knowledge-graph-style snapshots for top results containing tables or lists.
- **Did You Mean:** Built-in spell checking and suggestions for popular search queries.
- **Auto-DB Fetching:** Automatically downloads a pre-populated database from Google Drive if a local `search.db` file is not found.

## How to use the Crawler

The multithreaded crawler (`crawler.py`) is designed to navigate from given start URLs and populate your `search.db` database.

### Basic Usage
To quickly run the crawler starting from a specific URL using the default settings (max 50 pages, 5 threads):
```bash
python crawler.py https://example.com
```

### Examples and Arguments
The crawler has several flags to customize how it behaves:

**1. Restricting Allowed Domains**
Use `-d` or `--allowed-domains` to ensure the crawler only stays within certain domain families.
```bash
python crawler.py https://en.wikipedia.org/wiki/Main_Page -d wikipedia.org
```

**2. Crawling More Pages with More Threads**
Use `-m` to set a higher maximum page limit, and `-t` to launch more concurrent threads for faster fetching.
```bash
python crawler.py https://news.ycombinator.com/ -m 500 -t 15
```

**3. Saving to a Custom Database**
If you want to create a separate database (to avoid overwriting your main `search.db`), use `-o`.
```bash
python crawler.py https://github.com/ -o github_data.db
```

**4. Comprehensive Example**
Combine all arguments to scrape documentation across multiple domains heavily:
```bash
python crawler.py https://docs.python.org/3/ https://wikipedia.org/ -d python.org wikipedia.org -m 2000 -t 20 -o python_wiki.db
```

## Running the Web App

Once your database is populated natively or automatically downloaded, launch the search engine:

```bash
python app.py
```
Open your browser and navigate to `http://127.0.0.1:5001`.
