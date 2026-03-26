import requests
from bs4 import BeautifulSoup
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse
import json
import sys
import os
import logging
import argparse
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

# --- Constants ---
DEFAULT_USER_AGENT = "SEngineCrawler/2.1 (+https://github.com/gokuthug1)"
DEFAULT_REQUEST_DELAY = 0.5 
DEFAULT_TIMEOUT = 10 
DEFAULT_MAX_PAGES = 50
DEFAULT_DB_FILE = 'search.db'
DEFAULT_THREADS = 5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
log = logging.getLogger(__name__)

# Lock for thread-safe DB writes and set updates
db_lock = Lock()

def init_db(db_file):
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute('''
        CREATE TABLE IF NOT EXISTS pages (
            url TEXT PRIMARY KEY,
            title TEXT,
            text_snippet TEXT,
            images TEXT,
            videos TEXT,
            list_items TEXT,
            table_content TEXT
        )
    ''')
    # Indices for faster searching
    c.execute("CREATE INDEX IF NOT EXISTS idx_title ON pages(title);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_body ON pages(text_snippet);")
    conn.commit()
    conn.close()

def save_page_to_db(db_file, data):
    try:
        # DB operations must be thread-safe
        with db_lock:
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute('''
                INSERT OR REPLACE INTO pages 
                (url, title, text_snippet, images, videos, list_items, table_content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['url'], 
                data['title'], 
                data['text_snippet'], 
                json.dumps(data['images']), 
                json.dumps(data['videos']), 
                json.dumps(data['list_items']), 
                json.dumps(data['table_content'])
            ))
            conn.commit()
            conn.close()
    except Exception as e:
        log.error(f"Error saving to DB: {e}")

def url_exists_in_db(db_file, url):
    try:
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("SELECT 1 FROM pages WHERE url = ?", (url,))
        result = c.fetchone()
        conn.close()
        return result is not None
    except:
        return False

def normalize_url(base_url, link):
    try:
        abs_url = urljoin(base_url, link.strip())
        parsed = urlparse(abs_url)
        if parsed.scheme not in ['http', 'https']: return None
        # Normalize: remove fragment, force lowercase scheme/netloc
        return parsed._replace(fragment="", scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()
    except ValueError: return None

def get_robots_parser(session, domain):
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"https://{domain}/robots.txt")
    try:
        resp = session.get(f"https://{domain}/robots.txt", timeout=5)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        else:
            rp.allow_all = True
    except:
        rp.allow_all = True
    return rp

def parse_page(response):
    url = response.url
    found_links = []
    try:
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove scripts and styles
        for script in soup(["script", "style"]): script.extract()

        title = soup.title.string.strip() if soup.title and soup.title.string else 'No Title'
        
        text = soup.get_text(separator=' ', strip=True)
        text_snippet = ' '.join(text.split())[:800] # Cleaner text extraction

        images = []
        for img in soup.find_all('img', src=True):
            src = urljoin(url, img['src'])
            if src.startswith('http'):
                images.append({'src': src, 'alt': img.get('alt', '')})

        videos = []
        for v in soup.find_all('video', src=True): videos.append(urljoin(url, v['src']))
        for s in soup.find_all('source', src=True): videos.append(urljoin(url, s['src']))
        
        list_items = []
        for l in soup.find_all(['ul', 'ol']):
            items = [li.get_text(' ', strip=True) for li in l.find_all('li')]
            if items: list_items.append(items)

        table_content = []
        for t in soup.find_all('table'):
            rows = []
            for tr in t.find_all('tr'):
                cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td', 'th'])]
                rows.append(" | ".join(cells))
            if rows: table_content.append(rows)

        for a in soup.find_all('a', href=True):
            norm = normalize_url(url, a['href'])
            if norm: found_links.append(norm)

        data = {
            'url': url, 'title': title, 'text_snippet': text_snippet,
            'images': images, 'videos': list(set(videos)), 
            'list_items': list_items, 'table_content': table_content
        }
        return data, found_links
    except Exception as e:
        log.error(f"Error parsing {url}: {e}")
        return None, []

# --- Worker Function ---
def crawl_worker(url, db_file, visited, queue, domain_rules, user_agent):
    # Check visited safely
    with db_lock:
        if url in visited: return
        visited.add(url)
    
    # Check DB existence
    if url_exists_in_db(db_file, url):
        log.info(f"Skipping (In DB): {url}")
        return

    # Check Robots (Simplified: Assuming allow for this snippet or pre-checked)
    session = requests.Session()
    session.headers.update({'User-Agent': user_agent})
    
    try:
        response = session.get(url, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200 and 'text/html' in response.headers.get('Content-Type', ''):
            data, links = parse_page(response)
            if data:
                save_page_to_db(db_file, data)
                log.info(f"Saved: {url} ({len(links)} links)")
                
                # Add new links to queue safely
                with db_lock:
                    for link in links:
                        if link not in visited:
                            # Basic Domain constraint
                            if domain_rules:
                                domain = urlparse(link).netloc
                                if not any(domain.endswith(d) for d in domain_rules):
                                    continue
                            queue.append(link)
    except Exception as e:
        log.debug(f"Failed {url}: {e}")

# --- Main ---
def main():
    parser = argparse.ArgumentParser(description="Multithreaded Crawler")
    parser.add_argument("start_urls", nargs='+', help="Start URLs")
    parser.add_argument("-d", "--allowed-domains", nargs='*', default=[])
    parser.add_argument("-m", "--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("-o", "--output-db", default=DEFAULT_DB_FILE)
    
    args = parser.parse_args()
    
    init_db(args.output_db)
    
    # Queue and Visited set
    queue = list(args.start_urls)
    visited = set()
    
    # We use a ThreadPool to process the queue
    # Since queue grows dynamically, we iterate in chunks
    
    crawled_count = 0
    
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        while queue and crawled_count < args.max_pages:
            # Grab a batch of URLs
            batch = []
            with db_lock:
                while queue and len(batch) < args.threads * 2:
                    u = queue.pop(0)
                    if u not in visited: batch.append(u)
            
            if not batch: break
            
            futures = [
                executor.submit(crawl_worker, url, args.output_db, visited, queue, args.allowed_domains, DEFAULT_USER_AGENT)
                for url in batch
            ]
            
            # Wait for batch
            for f in futures: f.result()
            
            crawled_count += len(batch)
            log.info(f"Total Crawled: {crawled_count}")

if __name__ == "__main__":
    main()