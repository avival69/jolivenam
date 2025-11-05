#!/usr/bin/env python3
"""
checker.py
"""

import os, requests, json, time, traceback
from datetime import datetime
from dateutil import parser as dateparser

# ----- Config -----
KEYWORDS = [
    "new grad", "graduate", "entry", "fresher", "sde 1", "sde i",
    "software engineer i", "associate software engineer", "early-career",
    "entry level", "junior", "intern"
]

LOCATION_KEYWORDS = [
    "india", "bangalore", "bengaluru", "hyderabad", "pune",
    "mumbai", "gurgaon", "gurugram", "chennai", "noida",
    "delhi", "kochi", "trivandrum"
]

MAX_EMBEDS_PER_REQUEST = 6
COMPANIES_FILE = "companies.json"
STATE_FILE = "seen.json"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or ""

HEADERS = {
    "User-Agent": "JobWatcherBot/1.0 python-requests"
}

def load_json(path):
    try:
        with open(path,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path,"w",encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def matches_entry_level(title, description=""):
    text = (title + " " + description).lower()
    return any(k in text for k in KEYWORDS)

def matches_location(location):
    if not location:
        return False
    loc = location.lower()
    # ignore if remote/global/etc
    if "remote" in loc or "global" in loc or "anywhere" in loc:
        return False
    return any(k in loc for k in LOCATION_KEYWORDS)

def send_discord_embeds(embeds):
    if not WEBHOOK_URL:
        print("No WEBHOOK_URL set.")
        return
    requests.post(WEBHOOK_URL, json={"embeds": embeds})

def build_embed(company, title, location, url, posted=None, snippet=None):
    try:
        ts = dateparser.parse(posted).isoformat() if posted else datetime.utcnow().isoformat()
    except:
        ts = datetime.utcnow().isoformat()
    return {
        "title": title[:256],
        "url": url,
        "timestamp": ts,
        "description": snippet or "",
        "fields": [
            {"name": "Company", "value": company, "inline": True},
            {"name": "Location", "value": location or "N/A", "inline": True}
        ]
    }

def scrape_greenhouse(handles):
    jobs = []
    for handle in handles:
        try:
            r = requests.get(f"https://api.greenhouse.io/v1/boards/{handle}/jobs", headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            for j in r.json().get("jobs", []):
                title = j.get("title","")
                location = j.get("location",{}).get("name","")
                if not matches_entry_level(title, j.get("content","")): continue
                if not matches_location(location): continue
                jobs.append({
                    "signature": f"greenhouse|{handle}|{title}|{j.get('absolute_url')}",
                    "company": handle,
                    "title": title,
                    "location": location,
                    "url": j.get("absolute_url"),
                    "posted": j.get("updated_at"),
                    "snippet": (j.get("content") or "")[:280]
                })
        except:
            pass
    return jobs

def scrape_lever(handles):
    jobs = []
    for handle in handles:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{handle}", headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            for j in r.json():
                title = j.get("text","")
                location = j.get("categories",{}).get("location","")
                if not matches_entry_level(title, j.get("description","")): continue
                if not matches_location(location): continue
                jobs.append({
                    "signature": f"lever|{handle}|{title}|{j.get('hostedUrl')}",
                    "company": handle,
                    "title": title,
                    "location": location,
                    "url": j.get("hostedUrl"),
                    "posted": j.get("createdAt"),
                    "snippet": (j.get("description") or "")[:280]
                })
        except:
            pass
    return jobs

def scrape_workday(pairs):
    jobs = []
    for name, url in pairs:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            d = r.json()
            postings = d.get("jobPostings") or []
            for j in postings:
                title = j.get("title","")
                location = j.get("locations","")
                if not matches_entry_level(title, j.get("description","")): continue
                if not matches_location(location): continue
                jobs.append({
                    "signature": f"workday|{name}|{title}|{url}",
                    "company": name,
                    "title": title,
                    "location": location,
                    "url": url,
                    "posted": j.get("postingDate"),
                    "snippet": (j.get("description") or "")[:280]
                })
        except:
            pass
    return jobs

def main():
    companies = load_json(COMPANIES_FILE)
    state = load_json(STATE_FILE)

    new_jobs = []
    for scraper, key in [(scrape_greenhouse,"greenhouse"), (scrape_lever,"lever"), (scrape_workday,"workday")]:
        for j in scraper(companies.get(key, [])):
            if j["signature"] not in state:
                state[j["signature"]] = True
                new_jobs.append(j)

    save_json(STATE_FILE, state)

    if not new_jobs:
        print("No new jobs.")
        return

    embeds = [build_embed(j["company"], j["title"], j["location"], j["url"], j["posted"], j["snippet"]) for j in new_jobs]
    for i in range(0, len(embeds), MAX_EMBEDS_PER_REQUEST):
        send_discord_embeds(embeds[i:i+MAX_EMBEDS_PER_REQUEST])
        time.sleep(1)

if __name__ == "__main__":
    main()
