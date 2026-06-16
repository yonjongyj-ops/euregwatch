# Cloud Setup Guide (GitHub Actions) — for non-technical users

This makes your EU regulatory monitor run **automatically in the cloud, every
morning, whether or not anyone's computer is on**. Your whole team gets the
alerts in your Slack/Teams channel. You set this up once.

Total time: about 20–30 minutes. You do NOT need to know how to code.

---

## What "the cloud" means here
GitHub is a free website that stores code and can run it on a schedule on
*their* computers. We put your files there, give it three secret passwords
(your API key and your chat webhook), and tell it "run every morning." Done.

---

## Part 1 — Make a GitHub account and a place for the files

1. Go to **github.com** and sign up (free). Verify your email.
2. Click the **+** in the top-right → **New repository**.
3. Name it something like `eu-reg-watch`.
4. Set it to **Private** (important — this keeps your settings out of public view).
5. Tick **"Add a README file"** so the repo isn't empty.
6. Click **Create repository**.

You now have an empty "repository" (think: a folder that lives on GitHub).

---

## Part 2 — Upload the files

1. On your new repo page, click **Add file** → **Upload files**.
2. Drag in ALL of these from the `eu-watch` folder:
   - `eu_reg_watch.py`
   - `sources.py`
   - `config.yaml`  ← see the note below first!
   - `seen.sqlite`
   - `.gitignore`
3. **Before uploading `config.yaml`:** open `config.sample.yaml`, save a copy
   named `config.yaml`, and fill in your company profile, watchlist, and owners.
   **Leave the `slack_webhook` and `teams_webhook` lines blank/empty** — those
   get added secretly later, NOT in this file.
4. For the workflow file: GitHub needs it in a specific subfolder. In the upload
   box, when adding `watch.yml`, type this exact path in front of the filename:
   `.github/workflows/watch.yml`
   (Type `.github/workflows/` then the filename — GitHub creates the folders.)
5. Scroll down, click **Commit changes**.

> Tip: if dragging the folder structure is fiddly, upload the three `.py`/`.yaml`
> files and `seen.sqlite` first, commit, then do a second **Add file → Create
> new file**, name it `.github/workflows/watch.yml`, and paste the contents of
> `watch.yml` in. Commit again.

---

## Part 3 — Add your secret passwords

These are stored encrypted by GitHub and never shown in the files.

1. In your repo, click **Settings** (top menu).
2. Left sidebar: **Secrets and variables** → **Actions**.
3. Click **New repository secret**. Add each of these:

   | Name (type exactly) | Value |
   |---------------------|-------|
   | `ANTHROPIC_API_KEY` | your `sk-ant-...` key from console.anthropic.com |
   | `SLACK_WEBHOOK`     | your Slack incoming-webhook URL (or skip if using Teams) |
   | `TEAMS_WEBHOOK`     | your Teams webhook URL (or skip if using Slack) |

   Add one, click **Add secret**, repeat. You only need the chat webhook(s) you
   actually use — add Slack OR Teams OR both.

---

## Part 4 — Turn it on and test it

1. Click the **Actions** tab at the top of your repo.
2. If GitHub asks to enable Actions, click the green **enable** button.
3. In the left list, click **EU Reg Watch**.
4. Click the **Run workflow** button (right side) → **Run workflow**. This runs
   it immediately so you don't have to wait until morning.
5. Click into the run that appears. You'll see steps turn green as it works.
   Click **Run the monitor** to watch its output. Within a minute or two you
   should see new alerts land in your Slack/Teams channel.

If something's red, click the failed step to read the error — it's usually a
typo in a secret name or a webhook URL.

---

## Part 5 — It's now automatic

That's it. From now on it runs **every day at 07:00 UTC** on its own.

- **07:00 UTC = roughly 08:00 in Central Europe (winter) / 09:00 (summer).**
  GitHub only schedules in UTC — there is no timezone setting. To change the
  hour, edit `.github/workflows/watch.yml` and change the `7` in `"0 7 * * *"`.
- You can always hit **Run workflow** in the Actions tab to run it on demand.

---

## Sharing with your team
You don't share a link to this. **The alerts are the shared thing** — they post
into your Slack/Teams channel, so just add teammates to that channel. To let a
colleague manage the setup itself, go to repo **Settings → Collaborators** and
invite them.

---

## Two things to know (honestly)
1. **GitHub's free scheduled runs can occasionally be delayed or skipped** when
   their servers are busy. For regulatory monitoring that's fine — the next run
   catches up because each run looks back 3 days and the system remembers what it
   already sent. If a run is ever skipped, you won't get duplicates or miss items.
2. **This is an early-warning aid, not legal advice.** It flags and summarizes;
   your legal/compliance owner should confirm anything before you act.

## If alerts ever stop
Check the **Actions** tab for red/failed runs. The most common causes are an
expired/rotated `ANTHROPIC_API_KEY` or a changed webhook URL — update the secret
in Settings and run it again.
