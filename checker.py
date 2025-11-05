import requests
from datetime import datetime

WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_HERE"   # <<<< CHANGE THIS

# Keywords to detect entry-level roles
TITLE_KEYWORDS = [
    "intern", "internship", "new grad", "graduate", "entry",
    "software engineer i", "sde i", "sde 1", "jr", "junior"
]

# Only allow jobs in India cities
LOCATION_KEYWORDS = [
    "india", "bangalore", "bengaluru", "hyderabad", "pune",
    "mumbai", "gurgaon", "gurugram", "chennai", "noida",
    "delhi", "kochi", "trivandrum"
]

def matches_title(title):
    t = title.lower()
    return any(k in t for k in TITLE_KEYWORDS)

def matches_location(location):
    if not location:
        return False
    loc = location.lower()

    # ❌ Exclude remote / international
    if "remote" in loc or "global" in loc or "anywhere" in loc:
        return False

    # ✅ Allow India only
    return any(k in loc for k in LOCATION_KEYWORDS)

def send_discord(msg):
    requests.post(WEBHOOK_URL, json={"content": msg})

# ---------------- SCRAPERS ---------------- #

def check_greenhouse(comp, url):
    jobs = []
    r = requests.get(url).json()
    for job in r.get("jobs", []):
        title = job.get("title", "")
        location = job.get("location", {}).get("name", "")

        if matches_title(title) and matches_location(location):
            jobs.append(f"**{comp}** — {title}\n📍 {location}\n🔗 {job['absolute_url']}")
    return jobs

def check_lever(comp, url):
    jobs = []
    r = requests.get(url).json()
    for job in r:
        title = job.get("text", "")
        location = job.get("categories", {}).get("location", "")

        if matches_title(title) and matches_location(location):
            jobs.append(f"**{comp}** — {title}\n📍 {location}\n🔗 {job['hostedUrl']}")
    return jobs

def check_workday(comp, url):
    jobs = []
    r = requests.get(url).json()
    for job in r.get("jobPostings", []):
        title = job.get("title", "")
        location = job.get("locationsText", "") or job.get("location", "")

        if matches_title(title) and matches_location(location):
            jobs.append(f"**{comp}** — {title}\n📍 {location}\n🔗 {url}")
    return jobs

# ---------------- COMPANY LIST ---------------- #

COMPANIES = [
    ("Google", "https://boards-api.greenhouse.io/v1/boards/google/jobs"),
    ("Microsoft", "https://jobs.microsoft.com/resultFeed/query"),
    ("NVIDIA", "https://api.lever.co/v0/postings/nvidia"),
    ("Ola", "https://boards-api.greenhouse.io/v1/boards/ola/jobs"),
    ("Razorpay", "https://api.lever.co/v0/postings/razorpay"),
    ("Coinbase", "https://boards-api.greenhouse.io/v1/boards/coinbase/jobs"),
]

# ---------------- MAIN ---------------- #

def main():
    all_jobs = []

    for comp, url in COMPANIES:
        try:
            if "greenhouse" in url:
                all_jobs += check_greenhouse(comp, url)
            elif "lever" in url:
                all_jobs += check_lever(comp, url)
            elif "workday" in url:
                all_jobs += check_workday(comp, url)
        except:
            continue

    if not all_jobs:
        print("No new India jobs found.")
        return

    timestamp = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    send_discord(f"🔔 **New Job Matches (India Only)** — {timestamp}")

    for job in all_jobs:
        send_discord(job)
        print(job)

if __name__ == "__main__":
    main()
