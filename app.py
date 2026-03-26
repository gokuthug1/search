import os
import json
import math
import re
import sqlite3
import requests
import random
import difflib
from datetime import datetime, timedelta
from flask import Flask, render_template, request, send_from_directory, make_response, redirect

app = Flask(__name__)

# --- CONFIGURATION ---
DB_FILE = 'search.db'
GOOGLE_DRIVE_FILE_ID = '1pwl8dCWx6IOQ5rRiVHm5b_l9HklrK4XD' 
DEFAULT_PER_PAGE = 10
NSFW_KEYWORDS = [
    "porn", "xxx", "sex", "nude", "naked", "erotic", "adult", 
    "hentai", "fuck", "dick", "pussy", "cock", "boobs", "18+"
]

# --- GOOGLE DRIVE DOWNLOADER ---
def download_file_from_google_drive(id, destination):
    print(f"Database not found. Attempting to download from Google Drive (ID: {id})...")
    URL = "https://docs.google.com/uc?export=download"
    session = requests.Session()
    try:
        response = session.get(URL, params={'id': id}, stream=True)
        token = get_confirm_token(response)
        if token:
            params = {'id': id, 'confirm': token}
            response = session.get(URL, params=params, stream=True)
        save_response_content(response, destination)
        print("Download complete.")
        return True
    except Exception as e:
        print(f"Failed to download DB: {e}")
        return False

def get_confirm_token(response):
    for key, value in response.cookies.items():
        if key.startswith('download_warning'):
            return value
    return None

def save_response_content(response, destination):
    CHUNK_SIZE = 32768
    with open(destination, "wb") as f:
        for chunk in response.iter_content(CHUNK_SIZE):
            if chunk: f.write(chunk)

# --- DB HELPERS ---
def init_db_check():
    if not os.path.exists(DB_FILE):
        if GOOGLE_DRIVE_FILE_ID:
            if download_file_from_google_drive(GOOGLE_DRIVE_FILE_ID, DB_FILE):
                return
        print("Creating new empty database (Download failed or ID invalid).")
        conn = sqlite3.connect(DB_FILE)
        conn.execute('''CREATE TABLE IF NOT EXISTS pages (
            url TEXT PRIMARY KEY, title TEXT, text_snippet TEXT, 
            images TEXT, videos TEXT, list_items TEXT, table_content TEXT
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_title ON pages(title);")
        conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

# Run DB check on startup
with app.app_context():
    init_db_check()

def get_stats():
    stats = {"pages": 0, "images": 0, "videos": 0}
    try:
        conn = get_db_connection()
        stats["pages"] = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        
        # Native approximation based on actual stored data structure
        if stats["pages"] > 0:
            pages_with_images = conn.execute("SELECT COUNT(*) FROM pages WHERE images != '[]' AND images IS NOT NULL").fetchone()[0]
            stats["images"] = pages_with_images * 3  # Estimate avg 3 images per article
            
            pages_with_videos = conn.execute("SELECT COUNT(*) FROM pages WHERE videos != '[]' AND videos IS NOT NULL").fetchone()[0]
            stats["videos"] = pages_with_videos * 1  # Estimate avg 1 video per video-page
        conn.close()
    except: pass
    return stats

# --- LOGIC ---
def safe_json_loads(data):
    if not data: return []
    try: return json.loads(data)
    except: return []

def generate_mock_date():
    """Generates a random recent date to simulate 'Freshness'"""
    days = random.randint(0, 30)
    hours = random.randint(0, 23)
    dt = datetime.now() - timedelta(days=days, hours=hours)
    if days == 0:
        return f"{hours} hours ago"
    elif days < 7:
        return f"{days} days ago"
    else:
        return dt.strftime("%b %d, %Y")

def check_spelling(query):
    """Simple 'Did you mean' logic based on common terms"""
    # In a real app, this would query a dictionary or the DB index
    common_terms = ["python", "javascript", "tutorial", "recipe", "news", "weather", "calculator", "finance", "google"]
    
    # 1. Check exact match in common terms (if user typed partial)
    # 2. Check for close matches
    matches = difflib.get_close_matches(query.lower(), common_terms, n=1, cutoff=0.7)
    if matches and matches[0] != query.lower():
        return matches[0]
    return None

def process_query_intent(query, results):
    intent = {}
    q_lower = query.lower().strip()

    # Calculator
    if any(op in q_lower for op in "+-*/") and re.match(r'^[\d\s\.\+\-\*\/\(\)]+$', q_lower):
        try:
            res = eval(q_lower, {"__builtins__": None}, {})
            if isinstance(res, (int, float)):
                intent['feature'] = 'calculator'
                intent['calc_data'] = {'expression': query, 'result': round(res, 4)}
        except: pass

    # Timer
    timer_match = re.search(r'(\d+)\s*(s|sec|m|min|minute|h|hour)', q_lower)
    if 'timer' in q_lower and timer_match:
        val = int(timer_match.group(1))
        unit = timer_match.group(2)
        sec = val if unit.startswith('s') else (val*60 if unit.startswith('m') else val*3600)
        intent['feature'] = 'timer'
        intent['timer_data'] = {'seconds': sec}

    # Infobox (Knowledge Graph Mock)
    if results:
        best = next((r for r in results[:5] if q_lower in r['title'].lower()), None)
        if best:
            facts = best.get('table_content', []) or best.get('list_items', [])
            flat_facts = []
            for item in facts:
                if isinstance(item, list): flat_facts.extend(item)
                else: flat_facts.append(item)

            img_src = None
            if best.get('images'): img_src = best['images'][0]['src']

            intent['infobox'] = {
                'title': best['title'],
                'description': best['text_snippet'][:300] + '...',
                'url': best['url'],
                'image': img_src,
                'facts': flat_facts[:5]
            }
    return intent

def highlight(text, query):
    if not query or not text: return text
    # Escape query for regex and replace
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(lambda m: f"<b>{m.group(0)}</b>", text)

def is_safe(text):
    if not text: return True
    text = text.lower()
    return not any(w in text for w in NSFW_KEYWORDS)

# --- ROUTES ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'logo.png', mimetype='image/png')

@app.route('/')
def index():
    return render_template('home.html', stats=get_stats())

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        safe = request.form.get('safe_search')
        pp = request.form.get('per_page')
        resp = make_response(redirect('/'))
        resp.set_cookie('safe_search', 'on' if safe else 'off', max_age=60*60*24*365)
        resp.set_cookie('per_page', pp, max_age=60*60*24*365)
        return resp
    
    curr = {
        'safe_search': request.cookies.get('safe_search', 'on'),
        'per_page': request.cookies.get('per_page', str(DEFAULT_PER_PAGE))
    }
    return render_template('settings.html', settings=curr)

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'web')
    page = request.args.get('page', 1, type=int)
    
    safe_mode = request.cookies.get('safe_search', 'on') == 'on'
    try: per_page = int(request.cookies.get('per_page', DEFAULT_PER_PAGE))
    except: per_page = DEFAULT_PER_PAGE

    results = []
    total_results = 0
    intent = {}
    did_you_mean = None

    if query:
        did_you_mean = check_spelling(query)
        
        conn = get_db_connection()
        offset = (page - 1) * per_page
        sql_query = f"%{query}%"
        
        if search_type == 'web':
            rows = conn.execute(
                "SELECT * FROM pages WHERE title LIKE ? OR text_snippet LIKE ? LIMIT 300", 
                (sql_query, sql_query)
            ).fetchall()

            clean_results = []
            for row in rows:
                if safe_mode and not is_safe(row['title'] + ' ' + row['text_snippet']): continue
                
                item = dict(row)
                item['images'] = safe_json_loads(item['images'])
                item['videos'] = safe_json_loads(item['videos'])
                item['list_items'] = safe_json_loads(item['list_items'])
                item['table_content'] = safe_json_loads(item['table_content'])
                item['published'] = generate_mock_date()
                
                item['title_html'] = highlight(item['title'], query)
                item['text_snippet_html'] = highlight(item['text_snippet'], query)
                
                score = 0
                if query.lower() in item['title'].lower(): score += 10
                if query.lower() in item['text_snippet'].lower(): score += 2
                item['score'] = score
                
                clean_results.append(item)
            
            clean_results.sort(key=lambda x: x['score'], reverse=True)
            total_results = len(clean_results)
            results = clean_results[offset : offset + per_page]
            intent = process_query_intent(query, results)

        elif search_type == 'images':
            rows = conn.execute(
                "SELECT url, title, images FROM pages WHERE title LIKE ? OR images LIKE ? LIMIT 300", 
                (sql_query, sql_query)
            ).fetchall()

            temp_imgs = []
            for row in rows:
                imgs = safe_json_loads(row['images'])
                for img in imgs:
                    if safe_mode and not is_safe(img.get('alt', '')): continue
                    if query.lower() in img.get('alt', '').lower() or query.lower() in row['title'].lower():
                        temp_imgs.append({
                            'src': img['src'], 
                            'alt': img.get('alt', 'Image'),
                            'parent_url': row['url'], 
                            'parent_title': row['title']
                        })

            total_results = len(temp_imgs)
            results = temp_imgs[offset : offset + per_page]

        elif search_type == 'videos':
            rows = conn.execute(
                "SELECT url, title, videos FROM pages WHERE title LIKE ? OR videos LIKE ? LIMIT 300", 
                (sql_query, sql_query)
            ).fetchall()

            temp_vids = []
            for row in rows:
                vids = safe_json_loads(row['videos'])
                for vid in vids:
                    if safe_mode and not is_safe(vid): continue
                    if query.lower() in vid.lower() or query.lower() in row['title'].lower():
                        temp_vids.append({
                            'src': vid, 
                            'parent_url': row['url'], 
                            'parent_title': row['title']
                        })
            
            total_results = len(temp_vids)
            results = temp_vids[offset : offset + per_page]
        
        conn.close()

    total_pages = math.ceil(total_results / per_page)
    if page > total_pages and total_pages > 0: page = total_pages

    return render_template(
        'results.html', 
        query=query, results=results, search_type=search_type,
        stats=get_stats(), page=page, total_pages=total_pages, total_results=total_results,
        intent=intent, did_you_mean=did_you_mean
    )

if __name__ == '__main__':
    app.run(debug=True, port=5001)