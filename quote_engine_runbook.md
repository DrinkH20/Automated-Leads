# CLEAN AFFINITY — AUTOMATED LEADS RUNBOOK

## Overview

This system:

* Pulls leads from Gmail
* Processes them
* Geocodes addresses
* Determines service zone
* Writes to Google Sheets
* Creates/sends email drafts
* Runs automatically via cron on a DigitalOcean droplet

---

# CONNECT TO DROPLET

From PowerShell:

```
ssh root@134.209.50.116
```

---

# NAVIGATION

Main directories:

```
Repo (GitHub source):
/opt/quote_engine_repo

Live (what cron runs):
/opt/quote_engine_current
```

---

# UPDATE CODE (STANDARD DEPLOY)

### 1. Go to repo

```
cd /opt/quote_engine_repo
```

### 2. Pull latest code

```
git pull origin main
```

### 3. Re-link live directory

```
rm -rf /opt/quote_engine_current
ln -s /opt/quote_engine_repo /opt/quote_engine_current
```

---

# INSTALL / UPDATE DEPENDENCIES

### Activate virtual environment

```
cd /opt/quote_engine_current
source venv/bin/activate
```

### Install requirements

```
pip install -r requirements.txt
```

---

# MANUAL TEST RUN (CRITICAL)

Run exactly what cron runs:

```
bash /opt/quote_engine_current/runner.sh
```

Check logs:

```
tail -n 50 /opt/quote_engine_current/automation.log
```

---

# FORCE TEST (IGNORE TIME WINDOW)

Edit runner:

```
nano /opt/quote_engine_current/runner.sh
```

Temporarily bypass time check OR add:

```
echo "TEST MODE — running regardless of time" >> "$LOG_FILE"
```

Run again.

---

# CRON MANAGEMENT

### Check cron status

```
systemctl status cron
```

### Restart cron

```
systemctl restart cron
```

### View cron jobs

```
crontab -l
```

Expected entry:

```
* * * * * flock -n /tmp/quote_engine.lock /opt/quote_engine_current/runner.sh
```

---

# LOG MONITORING

### Live logs

```
tail -f /opt/quote_engine_current/automation.log
```

### Check recent runs

```
tail -n 100 /opt/quote_engine_current/automation.log
```

---

# ENVIRONMENT VARIABLES (.env)

Location:

```
/opt/quote_engine_current/.env
```

Example:

```
GOOGLE_MAPS_API_KEY=YOUR_KEY
GOOGLE_API_KEY=YOUR_KEY
```

Ensure runner loads it:

```
export $(grep -v '^#' /opt/quote_engine_current/.env | xargs)
```

---

# CACHE MANAGEMENT

Cache file:

```
geocode_cache.json
```

### Clear cache (fix errors / reduce corruption)

```
rm /opt/quote_engine_current/geocode_cache.json
```

---

# COMMON ERRORS + FIXES

## ModuleNotFoundError (dotenv, jinja2, xlwings, etc)

Fix:

```
pip install -r requirements.txt
```

---

## Google API key error

Error:

```
Google requires each request to have an API key
```

Fix:

* Confirm `.env` exists
* Confirm runner loads `.env`
* Confirm key name matches code

---

## Cron runs but script does nothing

Check:

* Time window logic in runner.sh
* Logs for "Outside allowed window"

---

## Works manually but not in cron

Cause:

* Missing env vars
* Wrong working directory

Fix:

* Ensure runner loads `.env`
* Use absolute file paths

---

## Zone detection failing

Check:

* geocode returning valid lat/lng
* cache file not corrupted
* polygon JSON paths correct

---

## Wrong email recipients

Cause:

* Variable mismatch in loop

Fix:

* Verify receiver_email mapping in autoemailing.py

---

# COST CONTROL (VERY IMPORTANT)

To avoid high Google API bills:

* Always use cache
* Ensure cache path is absolute
* Avoid repeated geocoding
* Delete corrupt cache entries
* Consider setting Google API quota limits

---

# SAFE DEPLOY CHECKLIST

Before updating production:

- [ ] Code runs locally
- [ ] No errors in console
- [ ] Requirements.txt updated
- [ ] Cache logic stable
- [ ] No test mode enabled
- [ ] Correct email sending logic
- [ ] Env variables correct

---

# NIGHTLY VERIFICATION

At ~6:30pm:

```
tail -f /opt/quote_engine_current/automation.log
```

You should see:

```
Runner fired
Automation run complete
```

---

# EMERGENCY RESET

If system is broken:

```
rm -rf /opt/quote_engine_current
cd /opt/quote_engine_repo
git reset --hard origin/main
ln -s /opt/quote_engine_repo /opt/quote_engine_current
systemctl restart cron
```

---

# FINAL NOTE

This system is production automation. Always:

* Test manually before relying on cron
* Watch logs during first run after deploy
* Keep cache + env + dependencies aligned

---

# GMAIL AUTH — HOW IT ACTUALLY WORKS

The automation authenticates to Gmail with an OAuth token cached at
`credentials/token.pickle`.

**`credentials/` is gitignored.** `git pull` will never deliver a token to the
droplet. It has to be copied by hand. This is the single most common reason the
automation is "broken" — auth, not code.

### Re-authorize (when auth fails)

On your PC, in the repo:

```
python gmail_auth.py
```

A browser opens; sign in as hello@cleanaffinity.com and approve all three
permissions. Then copy the token to the droplet, from a LOCAL PowerShell window:

```
scp "C:\Users\Joel Jones\Documents\GitHub\Automated Leads\credentials\token.pickle" root@134.209.50.116:/opt/quote_engine_repo/credentials/token.pickle
```

Verify on the droplet:

```
cd /opt/quote_engine_current && ./venv/bin/python -c "from gmail_auth import get_gmail_credentials; print('OK', get_gmail_credentials().valid)"
```

### The 7-day trap

If the OAuth consent screen's publishing status is **Testing**, Google expires
every refresh token after 7 days and the automation dies mid-week with
`invalid_grant: Token has been expired or revoked`.

Keep it on **In production**: Google Cloud Console > project
`vibrant-arcanum-432521-q2` > APIs & Services > OAuth consent screen (newer
console calls it Audience) > Publishing status. The "unverified app" warning
that comes with publishing is expected and harmless for a single user.

Changing the Google account password also revokes the token. Same fix:
re-authorize and copy it up.

---

# WHICH MACHINE AM I ON?

Most wasted time comes from running a command in the wrong place. Check the
prompt before pasting:

| Prompt | Machine | What runs here |
|---|---|---|
| `PS C:\Users\Joel Jones>` | Your PC (Windows) | `git push`, `scp`, `python gmail_auth.py` |
| `root@ubuntu-s-1vcpu-1gb-sfo2-01:~#` | The droplet (Linux) | `git pull`, `tail`, `systemctl`, test runs |

Windows paths (`C:\...`) mean nothing on the droplet. `&&` is a syntax error in
Windows PowerShell 5.1. Paste multi-line blocks ONE LINE AT A TIME over SSH —
the terminal splits them and bash tries to run Python as shell commands.

To get from the droplet back to your PC: `exit`.

---

# LOG ROTATION

`automation.log` has no rotation by default and grew to 866MB. Install the
config once, on the droplet:

```
cp /opt/quote_engine_current/deploy/logrotate-quote-engine /etc/logrotate.d/quote-engine
logrotate -d /etc/logrotate.d/quote-engine
logrotate -f /etc/logrotate.d/quote-engine
```

Check size any time with `ls -lh /opt/quote_engine_current/automation.log`.

---

# NOT IN VERSION CONTROL

These exist only on the droplet. A rebuild loses them — back them up before any
destructive maintenance:

- `runner.sh` — the script cron actually invokes, including the time-window check
- `credentials/` — OAuth client, service account, token
- `.env` — API keys
- `venv/` — rebuildable with `pip install -r requirements.txt`

---

# FAILURE MODES SEEN IN PRODUCTION

| Symptom in the log | Cause | Fix |
|---|---|---|
| `invalid_grant: Token has been expired or revoked` | Password change, or 7-day Testing expiry | Re-authorize, scp token up |
| `No usable Gmail token at ...` | Token missing on that machine | scp it up |
| `TypeError: float() argument must be ... not 'NoneType'` | Lead submitted with blank SQFT | Fixed Sep 2026 — leads without sqft now skip the quote instead of aborting the run |
| `'biWeekly' is not in list` | camelCase service type vs lowercase chart | Fixed Sep 2026 — ranking normalizes case |
| Runs complete but nothing sends, leads vanish | Blanket `Automations` label sweep discarded failed leads | Fixed Sep 2026 — only processed messages are unlabeled, failures retry |
