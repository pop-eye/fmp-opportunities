# fmp-opportunities

Weekly feeds of graduate jobs, placements, and creative industry events for BA Future Media Production students at Manchester Metropolitan University.

The project generates RSS 2.0 XML feeds, an iCalendar `.ics` file, JSON data files, and accessible static HTML pages in [docs/](docs/) for publishing via GitHub Pages and embedding inside Moodle.

The website's colours and layout can be adjusted using the variables at the top of [docs/styles.css](docs/styles.css).

Each feed page has an optional map. Markers represent approximate centres of recognised towns, cities and some Manchester neighbourhoods, and reflect the current filters. Select a marker and then a listing to view it on the page. Use the mouse wheel, pinch gestures or the map buttons to zoom. Remote listings and locations that are unknown, ambiguous, or outside the built in list remain in the results below the map. Opening the map loads Leaflet from unpkg and map tiles from OpenStreetMap. These services receive the visitor's IP address and normal browser request information. No geocoding service or location tracking is used. Tiles are subject to the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

Students can search, filter and sort each feed, or save listings in their browser. They can find saved listings using the saved links on the home page or each feed page, or the Saved only filter. Saved listing identifiers stay on that device and are not sent to a server. They can disappear if browser data is cleared or the listing is no longer available. If browser storage is blocked, the page reports that saving is unavailable. The website hides listings with known past dates between updates, but dates and availability can be missing or change. Students should check the original source.

The placements feed searches the Reed API across creative disciplines and includes relevant internships from the gamesJobs RSS feed. Reed requires `REED_API_KEY`; gamesJobs permits light, polite RSS access, and its feed is limited to recent entries. The placements page also links to Higherin, Channel 4, Sky and Prospects for manual browsing. Those links are not automatically imported, and the availability and eligibility of individual programmes must be checked on the original sites.

## Project structure

* [run.py](run.py): command line entry point.
* [sources.yaml](sources.yaml): editable list of sources for `jobs`, `placements`, and `events`.
* [keywords.yaml](keywords.yaml): relevance include weights and exclude terms.
* [src/fmp_opportunities/core/](src/fmp_opportunities/core/): shared data model, configuration loader, polite HTTP fetcher, keyword filter, deduplicator, state manager, writers, and operational helpers.
* [src/fmp_opportunities/tools/](src/fmp_opportunities/tools/): thin modules for `jobs`, `placements`, and `events`.
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

* **Reed API** (optional, for Jobs): register at [Reed Developers](https://www.reed.co.uk/developers/jobseeker) and set `REED_API_KEY`.
* **Adzuna API** (optional, for Jobs): register at [Adzuna Developer](https://developer.adzuna.com/) and set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
* **Email failure alerts** (optional): set `SMTP_HOST`, `SMTP_PORT` (default `587`), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, and `SMTP_USE_TLS` (`true` or `false`).

If `REED_API_KEY` or `ADZUNA_APP_ID` is not set, those sources are skipped cleanly without failing the run.

## 3. Running manually

Run a dry run without writing files or pushing to GitHub:

```powershell
.venv\Scripts\python.exe run.py --tool all --dry-run --verbose
```

Generate all feeds locally without pushing to GitHub:

```powershell
.venv\Scripts\python.exe run.py --tool all --no-push --site-url "https://YOUR_USERNAME.github.io/YOUR_REPO/"
```

Run a single tool (`jobs`, `placements`, or `events`):

```powershell
.venv\Scripts\python.exe run.py --tool jobs --no-push
```

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

You do not need to edit core Python code to add an RSS, iCal, or CSS selector HTML source. Open [sources.yaml](sources.yaml) and add an entry under `jobs`, `placements`, or `events`:

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

* Add positive terms and weights under `global.include` or under a specific tool (`jobs`, `placements`, `events`).
* Add unwanted terms (such as senior roles) under `exclude`. Any listing matching an `exclude` term is dropped.
* Adjust `min_score` per tool if too many or too few listings are kept.
* Run `run.py --tool all --dry-run --verbose` to see the exact `KEEP` and `DROP` score and matched terms for every listing.

## 9. Troubleshooting

* **Too few or zero jobs kept**: run with `--dry-run --verbose` to see why items were dropped, and configure `REED_API_KEY` or `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` for broader Manchester coverage.
* **Suspicious drop warning**: if a run returns fewer than half of last week's items, the script keeps the previous `docs/` outputs and logs a warning in `logs/weekly_summary.txt`.
* **Source returns HTTP 403**: some sites use bot protection that blocks automated requests. Set `enabled: false` for that source in [sources.yaml](sources.yaml).
* **Git push fails in Task Scheduler**: ensure Git credentials are cached (`git config --global credential.helper manager`) and test `git push` manually once from PowerShell.
* **Stale cache during testing**: delete files inside `state/cache/` if you want to force fresh downloads immediately (cache expires automatically after 6 hours).
