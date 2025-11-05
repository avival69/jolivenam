#!/usr/bin/env python3
"""
checker.py

- Reads companies.json (greenhouse, lever, workday)
- Polls public APIs (Greenhouse/Lever) and tries Workday endpoints
- Filters for entry-level roles by KEYWORDS
- Persists seen job signatures to seen.json
- Sends detailed Discord embed messages to WEBHOOK_URL (from env)
"""

import os, requests, json, time, traceback
from datetime import datetime
from dateutil import parser as dateparser

# ----- Config -----
KEYWORDS = [
    "new grad", "graduate", "entry", "fresher", "sde 1", "sde i",
    "software engineer i", "software engineer i", "intern", "graduate",
    "associate software engineer", "early-career", "entry level", "junior"
]
MAX_EMBEDS_PER_REQUEST = 6  # be conservative with Discord rate limits
COMPANIES_FILE = "companies.json"
STATE_FILE = "seen.json"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or ""  # recommended: set as GitHub Secret

HEADERS = {
    "User-Agent": "JobWatcherBot/1.0 (+https://github.com/yourname/job-watcher) python-requests"
}

# ----- Utility -----
def load_json(path):
    try:
        with open(path,"r",encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print("Error loading JSON:", e)
        return {}

def save_json(path, data):
    with open(path,"w",encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def matches_entry_level(title, description=""):
    t = (title or "").lower()
    d = (description or "").lower()
    for k in KEYWORDS:
        if k in t or k in d:
            return True
    return False

# ----- Notifiers -----
def send_discord_embeds(embeds):
    if not WEBHOOK_URL:
        print("No WEBHOOK_URL set. Skipping Discord send.")
        return False, "no webhook"
    # Discord expects {"embeds": [...]}
    payload = {"embeds": embeds}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, headers={"Content-Type":"application/json"})
        if r.status_code // 100 == 2:
            return True, "ok"
        else:
            return False, f"{r.status_code} {r.text}"
    except Exception as e:
        return False, str(e)

def build_embed(company, title, location, url, posted=None, snippet=None):
    ts = None
    try:
        if posted:
            # try parse and format as ISO
            ts = dateparser.parse(posted).isoformat()
    except Exception:
        ts = None
    embed = {
        "title": title[:256] if title else "New Job",
        "description": snippet or "",
        "url": url or "",
        "timestamp": ts or datetime.utcnow().isoformat(),
        "fields": [
            {"name": "Company", "value": company, "inline": True},
            {"name": "Location", "value": location or "Remote/Unspecified", "inline": True}
        ]
    }
    return embed

# ----- Scrapers -----
def scrape_greenhouse(handles):
    jobs = []
    for handle in handles:
        try:
            url = f"https://boards.greenhouse.io/{handle}/jobs"
            api = f"https://boards.greenhouse.io/{handle}/jobs?content=true"  # page returns HTML but greenhouse api endpoint exists
            # There's also a JSON end-point: https://boards.greenhouse.io/embed/job_board?for={handle}&... but we'll attempt the v1 API:
            api_json = f"https://api.greenhouse.io/v1/boards/{handle}/jobs"
            r = requests.get(api_json, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                # fallback: try jobs embed (may be HTML)
                # We'll attempt to parse JSON only if available
                print(f"Greenhouse {handle} returned {r.status_code}")
                continue
            data = r.json()
            for j in data.get("jobs", []):
                title = j.get("title") or ""
                url_job = j.get("absolute_url") or j.get("url") or f"https://boards.greenhouse.io/{handle}/jobs/{j.get('id')}"
                location = j.get("location", {}).get("name") if isinstance(j.get("location"), dict) else j.get("location")
                content = j.get("content") or ""
                posted = j.get("updated_at") or j.get("created_at") or j.get("created")
                if matches_entry_level(title, content):
                    signature = f"greenhouse|{handle}|{title}|{url_job}"
                    jobs.append({
                        "signature": signature,
                        "company": handle,
                        "title": title,
                        "location": location,
                        "url": url_job,
                        "posted": posted,
                        "snippet": content[:280]
                    })
        except Exception as e:
            print("Greenhouse error for", handle, ":", e)
    return jobs

def scrape_lever(handles):
    jobs = []
    for handle in handles:
        try:
            api = f"https://api.lever.co/v0/postings/{handle}?mode=json"
            r = requests.get(api, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"Lever {handle} returned {r.status_code}")
                continue
            data = r.json()
            for j in data:
                title = j.get("text") or j.get("title") or ""
                url_job = j.get("hostedUrl") or j.get("applyUrl") or j.get("id")
                location = j.get("categories", {}).get("location") if j.get("categories") else None
                posted = j.get("datePosted") or j.get("createdAt")
                content = j.get("description") or j.get("text") or ""
                if matches_entry_level(title, content):
                    signature = f"lever|{handle}|{title}|{url_job}"
                    jobs.append({
                        "signature": signature,
                        "company": handle,
                        "title": title,
                        "location": location,
                        "url": url_job,
                        "posted": posted,
                        "snippet": (content or "")[:280]
                    })
        except Exception as e:
            print("Lever error for", handle, ":", e)
    return jobs

def scrape_workday(pairs):
    jobs = []
    for name, url in pairs:
        try:
            # Many Workday endpoints are custom; try generic GET and try to parse json if present
            # We'll attempt a GET and check for jobPostings or position data in JSON
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"Workday {name} returned {r.status_code} for {url}")
                continue
            # try parse JSON
            try:
                data = r.json()
            except Exception:
                data = None
            # common patterns:
            if data:
                # Try jobPostings
                postings = []
                if isinstance(data, dict):
                    # search for lists containing 'title' keys
                    def find_postings(obj):
                        found = []
                        if isinstance(obj, dict):
                            for k,v in obj.items():
                                if isinstance(v, list):
                                    for item in v:
                                        if isinstance(item, dict) and ("title" in item or "jobTitle" in item):
                                            found.append(item)
                                else:
                                    found += find_postings(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                found += find_postings(item)
                        return found
                    postings = find_postings(data)
                if postings:
                    for j in postings:
                        title = j.get("title") or j.get("jobTitle") or ""
                        url_job = j.get("externalUrl") or j.get("absoluteUrl") or url
                        location = j.get("location") or j.get("jobLocations")
                        posted = j.get("postingDate") or j.get("startDate") or None
                        snippet = j.get("summary") or ""
                        if matches_entry_level(title, snippet):
                            signature = f"workday|{name}|{title}|{url_job}"
                            jobs.append({
                                "signature": signature,
                                "company": name,
                                "title": title,
                                "location": location,
                                "url": url_job,
                                "posted": posted,
                                "snippet": snippet[:280]
                            })
                else:
                    # fallback: skip
                    continue
            else:
                # if no json, skip for now
                continue
        except Exception as e:
            print("Workday error for", name, ":", e)
    return jobs

# ----- Main orchestration -----
def main():
    print("Job watcher starting:", datetime.utcnow().isoformat())
    companies = load_json(COMPANIES_FILE)
    if not companies:
        print("No companies.json found or empty; exiting.")
        return
    greenhouse = companies.get("greenhouse", [])
    lever = companies.get("lever", [])
    workday = companies.get("workday", [])

    # Load state
    state = load_json(STATE_FILE)
    if not isinstance(state, dict):
        state = {}

    new_jobs = []

    try:
        print(f"Scraping Greenhouse: {len(greenhouse)} handles")
        gjobs = scrape_greenhouse(greenhouse)
        print("Greenhouse found:", len(gjobs))
        print(f"Scraping Lever: {len(lever)} handles")
        ljobs = scrape_lever(lever)
        print("Lever found:", len(ljobs))
        print(f"Scraping Workday: {len(workday)} entries")
        wjobs = scrape_workday(workday)
        print("Workday found:", len(wjobs))

        all_jobs = gjobs + ljobs + wjobs

        # Deduplicate & filter using state
        for j in all_jobs:
            sig = j.get("signature")
            if not sig:
                continue
            if sig in state:
                continue
            state[sig] = {"seen_at": datetime.utcnow().isoformat()}
            new_jobs.append(j)

        print("New jobs to notify:", len(new_jobs))

        # Build embeds and send in batches
        embeds = []
        for job in new_jobs:
            embed = build_embed(
                company=job.get("company"),
                title=job.get("title"),
                location=job.get("location"),
                url=job.get("url"),
                posted=job.get("posted"),
                snippet=job.get("snippet")
            )
            embeds.append(embed)
            # send in batches to avoid huge payloads
            if len(embeds) >= MAX_EMBEDS_PER_REQUEST:
                ok, info = send_discord_embeds(embeds)
                print("Discord send result:", ok, info)
                time.sleep(1.2)
                embeds = []

        if embeds:
            ok, info = send_discord_embeds(embeds)
            print("Discord send result:", ok, info)

    except Exception as e:
        print("Main error:", e)
        traceback.print_exc()
    finally:
        save_json(STATE_FILE, state)
        print("Done. State saved.")

if __name__ == "__main__":
    main()
