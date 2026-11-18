# fmp-opportunities

Weekly feeds of graduate jobs, placements, apprenticeships, and creative industry events for BA Future Media Production students at Manchester Metropolitan University.

The project generates RSS 2.0 XML feeds, an iCalendar `.ics` file, JSON data files, and accessible static HTML pages in [docs/](docs/) for publishing via GitHub Pages and embedding inside Moodle.

The website's colours and layout can be adjusted using the variables at the top of [docs/styles.css](docs/styles.css).

Each feed page has an optional map. Markers represent approximate centres of recognised towns, cities and some Manchester neighbourhoods, and reflect the current filters. Select a marker and then a listing to view it on the page. Use the mouse wheel, pinch gestures or the map buttons to zoom. Remote listings and locations that are unknown, ambiguous, or outside the built in list remain in the results below the map. Opening the map loads Leaflet from unpkg and map tiles from OpenStreetMap. These services receive the visitor's IP address and normal browser request information. No geocoding service or location tracking is used. Tiles are subject to the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

Students can search, filter and sort each feed, or save listings in their browser. They can find saved listings using the saved links on the home page or each feed page, or the Saved only filter. Saved listing identifiers stay on that device and are not sent to a server. They can disappear if browser data is cleared or the listing is no longer available. If browser storage is blocked, the page reports that saving is unavailable. The website hides listings with known past dates between updates, but dates and availability can be missing or change. Students should check the original source.

The events page also has a monthly calendar. It follows the active filters; select a highlighted date to open its event listings. Multi-day events appear on each date in their stated range. Events without a known start date remain in the list but cannot appear on the calendar.

For UKIE events, dates are read from each individual event card rather than from neighbouring listings. Ambiguous multiple dates are left unstated and a warning is logged rather than assuming a continuous range.

Event sources are listed under `events` in [sources.yaml](sources.yaml). FACT Liverpool, the Whitworth and Eventbrite are recorded there for manual browsing, but disabled for automated imports. FACT and the Whitworth need permission and parser checks; Eventbrite prohibits automated scraping in its terms. BEYOND Conference and Factory International are configured for automatic checks.

The placements feed searches the Reed API across creative disciplines and includes relevant internships from the gamesJobs RSS feed. Reed requires `REED_API_KEY`; gamesJobs permits light, polite RSS access, and its feed is limited to recent entries. The placements page also links to Higherin, Channel 4, Sky and Prospects for manual browsing. Those links are not automatically imported, and the availability and eligibility of individual programmes must be checked on the original sites.

The apprenticeships feed searches the official Find an apprenticeship Display Advert API for English vacancies in the Creative and design and Digital routes, the Reed API using creative search terms, and the gamesJobs RSS feed. Relevant role terms in [keywords.yaml](keywords.yaml) filter the results. The official API and Reed require separate keys; gamesJobs may have no apprenticeship listings. The DfE search is limited to 50 pages per run and logs a warning if more pages are available. Results may be incomplete, so the page also links to the official search for manual browsing. Check whether each opportunity is suitable alongside existing studies.

## Project structure

* [run.py](run.py): command line entry point.
* [sources.yaml](sources.yaml): editable list of sources for `jobs`, `placements`, `apprenticeships`, and `events`.
* [keywords.yaml](keywords.yaml): relevance include weights and exclude terms.
* [src/fmp_opportunities/core/](src/fmp_opportunities/core/): shared data model, configuration loader, polite HTTP fetcher, keyword filter, deduplicator, state manager, writers, and operational helpers.
* [src/fmp_opportunities/tools/](src/fmp_opportunities/tools/): thin modules for `jobs`, `placements`, `apprenticeships`, and `events`.
* [docs/](docs/): generated feeds and static HTML pages for GitHub Pages.
* [state/](state/): local JSON state (`state.json`) and HTTP cache (`cache/`).
* [logs/](logs/): rotating log file (`fmp_opportunities.log`) and weekly summary (`weekly_summary.txt`).

## 1. Local Python setup on Windows

1. Ensure Python 3.11 or later is installed (`python --version`).
2. Open PowerShell in the project folder and create a virtual environment:

```powershell
python -m venv .venv
```

3. Install the project and its dependencies into the virtual environment:

```powershell
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

4. Run the unit tests to confirm everything works:

```powershell
.venv\Scripts\python.exe -m pytest -v
```

## 2. Optional API keys and email alerts

Set environment variables in Windows (User environment variables via *Edit the system environment variables*, or in PowerShell before running):

* **Reed API** (optional, for jobs, placements and apprenticeships): register at [Reed Developers](https://www.reed.co.uk/developers/jobseeker) and set `REED_API_KEY`.
* **Find an apprenticeship API** (optional, for apprenticeships): [register for an individual Display Advert API key](https://developer.apprenticeships.education.gov.uk/third-party-accounts/register), then set `DFE_APPRENTICESHIPS_API_KEY`. The API key stays on your computer and is sent only to the API. Read the [official API guidance](https://developer.apprenticeships.education.gov.uk/) before using it.
* **Adzuna API** (optional, for Jobs): register at [Adzuna Developer](https://developer.adzuna.com/) and set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
* **Email failure alerts** (optional): set `SMTP_HOST`, `SMTP_PORT` (default `587`), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, and `SMTP_USE_TLS` (`true` or `false`).

If the relevant API key is not set, that source is skipped with a warning. Without the DfE or Reed key, the apprenticeships feed relies on gamesJobs and may be empty.

## 3. Running manually

Run a dry run without writing files or pushing to GitHub:

```powershell
.venv\Scripts\python.exe run.py --tool all --dry-run --verbose
```

Generate all feeds locally without pushing to GitHub:

```powershell
.venv\Scripts\python.exe run.py --tool all --no-push --site-url "https://YOUR_USERNAME.github.io/YOUR_REPO/"
```

Run a single tool (`jobs`, `placements`, `apprenticeships`, or `events`):

```powershell
.venv\Scripts\python.exe run.py --tool jobs --no-push
```

For apprenticeships alone, use `--tool apprenticeships`. Until the first feed run, the new page reports that its feed has not been generated. When running one tool, the combined RSS also includes existing JSON outputs from the other tools.

Run and automatically commit and push changes in `docs/` to GitHub:

```powershell
.venv\Scripts\python.exe run.py --tool all --site-url "https://YOUR_USERNAME.github.io/YOUR_REPO/"
```

## 4. GitHub Pages setup

1. Create a new repository on GitHub (for example `fmp-opportunities`).
2. Initialise Git in your local project folder, commit all files, and push to `main`:

```powershell
git init
git add .
git commit -m "Initial fmp-opportunities setup"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

3. In GitHub, open your repository and go to **Settings** > **Pages**.
4. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
5. Select branch `main` and folder `/docs`, then click **Save**.
6. Wait one to two minutes. Your site will be live at `https://YOUR_USERNAME.github.io/YOUR_REPO/`.

## 5. Windows Task Scheduler setup

Set up a weekly task so the script runs automatically, uses the virtual environment, and catches up if your PC was switched off.

1. Open **Task Scheduler** and click **Create Task** (do not use Create Basic Task, because you need the missed task option).
2. On the **General** tab:
   * Name: `FMP Opportunities Weekly`
   * Select **Run whether user is logged on or not** (or **Run only when user is logged on** if your Git credential helper requires an active desktop session).
3. On the **Triggers** tab, click **New**:
   * Begin the task: **On a schedule**
   * **Weekly**, pick a quiet day and time (for example Monday at `08:00`).
4. On the **Actions** tab, click **New**:
   * Action: **Start a program**
   * Program/script: `E:\myProjects\FMP job placement event scraper\.venv\Scripts\python.exe`
   * Add arguments: `run.py --tool all --site-url "https://YOUR_USERNAME.github.io/YOUR_REPO/"`
   * Start in: `E:\myProjects\FMP job placement event scraper`
5. On the **Settings** tab:
   * Tick **Run task as soon as possible after a scheduled start is missed**.
   * Tick **If the task fails, restart every** `10 minutes` (up to `2` attempts).
6. Click **OK** and test it once by right clicking the task and choosing **Run**.

## 6. Moodle integration

Replace `https://YOUR_USERNAME.github.io/YOUR_REPO` below with your actual GitHub Pages URL.

### Remote RSS feeds block

1. In your Moodle course, turn **Edit mode** on.
2. Add a **Remote RSS feeds** block.
3. Click the gear icon on the block and choose **Configure Remote RSS feeds block**.
4. Click **Add/edit feeds**, then **Add a new feed**.
5. Paste one of the feed URLs:
   * Jobs: `https://YOUR_USERNAME.github.io/YOUR_REPO/jobs.xml`
   * Placements: `https://YOUR_USERNAME.github.io/YOUR_REPO/placements.xml`
   * Apprenticeships: `https://YOUR_USERNAME.github.io/YOUR_REPO/apprenticeships.xml`
   * Events: `https://YOUR_USERNAME.github.io/YOUR_REPO/events.xml`
   * All combined: `https://YOUR_USERNAME.github.io/YOUR_REPO/all.xml`

### Calendar `.ics` subscription

1. Open the Moodle **Calendar** and click **Import or export calendars** (or **Manage subscriptions**).
2. Click **Import calendar**.
3. Choose **Calendar URL** and paste `https://YOUR_USERNAME.github.io/YOUR_REPO/events.ics`.
4. Set the refresh interval to weekly and save.

### Embedding the interactive page in a Moodle Page

Moodle strips JavaScript from normal page content, so embed the static HTML page inside an `<iframe>` using the HTML editor (`</>` button):

```html
<iframe
  src="https://YOUR_USERNAME.github.io/YOUR_REPO/index.html"
  title="BA Future Media Production Opportunities Feed"
  width="100%"
  height="850"
  style="border: 1px solid #d1d5db; border-radius: 8px;"
  loading="lazy">
</iframe>
```

You can also link directly to `jobs.html`, `placements.html`, or `events.html` in separate Moodle pages if preferred.

## 7. Adding a source

You do not need to edit core Python code to add an RSS, iCal, or CSS selector HTML source. Open [sources.yaml](sources.yaml) and add an entry under `jobs`, `placements`, `apprenticeships`, or `events`:

```yaml
  - name: Example Creative Board
    type: rss
    url: https://example.org/creative-jobs.xml
    enabled: true
    rate_limit_seconds: 2.0
    options:
      default_location: Manchester
```

For a simple HTML page, use `type: html` with `selectors`:

```yaml
  - name: Example Studio Careers
    type: html
    url: https://example.org/careers
    enabled: true
    rate_limit_seconds: 2.0
    selectors:
      item: .job-card
      title: h2 a
      link: h2 a
      location: .job-location
      summary: .job-summary
```

Always check `robots.txt` and the site's terms before enabling a new source.

## 8. Tuning keywords

Open [keywords.yaml](keywords.yaml):

* Add positive terms and weights under `global.include` or under a specific tool (`jobs`, `placements`, `apprenticeships`, `events`).
* Add unwanted terms (such as senior roles) under `exclude`. Any listing matching an `exclude` term is dropped.
* Jobs must also match a term under `jobs.required_any` in their title or summary, or a term under `jobs.required_title_any` in their title. Employer names, locations and generic words such as `digital` cannot satisfy this check by themselves. Add terms for relevant roles that are being missed. Placements and events do not use these job-specific rules.
* Adjust `min_score` per tool if too many or too few listings are kept.
* Run `run.py --tool all --dry-run --verbose` to see the exact `KEEP` and `DROP` score and matched terms for every listing.
* A listing fetched and rejected on a later run is removed from saved state rather than restored, unless the suspicious drop safeguard keeps the previous outputs. Listings not fetched can still remain for up to 14 days. The optional local LLM is a second opinion, not a guarantee of relevance. If its reply is invalid or the service is unavailable, the warning is logged and the keyword result is used.

## 9. Troubleshooting

* **Too few or zero jobs kept**: run with `--dry-run --verbose` to see why items were dropped, and configure `REED_API_KEY` or `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` for broader Manchester coverage.
* **Suspicious drop warning**: if a run returns fewer than half of last week's items, the script keeps the previous `docs/` outputs and logs a warning in `logs/weekly_summary.txt`.
* **Source returns HTTP 403**: some sites use bot protection that blocks automated requests. Set `enabled: false` for that source in [sources.yaml](sources.yaml).
* **Git push fails in Task Scheduler**: ensure Git credentials are cached (`git config --global credential.helper manager`) and test `git push` manually once from PowerShell.
* **Stale cache during testing**: delete files inside `state/cache/` if you want to force fresh downloads immediately (cache expires automatically after 6 hours).
