# Wayfinder

Searches all possibilities to deliver optimal BCEN seed navigation.

A Battle Cats (English version) pull planner with two modes: **Rare** finds the best way to spend rare tickets,
cat food, platinum and legend tickets on your bc.godfat.org seed; **Normal** plans cat-ticket and lucky-ticket
pulls on your bc-normal-seed-tracking seed. Needs Python 3.10 or newer and an internet connection.

## Run

Get the code:

```
git clone https://github.com/matthewychen/Wayfinder.git
cd Wayfinder
```

Windows: double-click `run.bat`, or from this folder:

```
.
un.bat
```

macOS, Linux or Git Bash:

```
./run.sh
```

It opens http://localhost:8501. The first run builds `.venv` and installs the requirements (a few
minutes); later runs start in seconds. Another port: `.
un.bat 8600` or `./run.sh 8600`.

## Run by hand

Windows:

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

macOS or Linux:

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

## Two planners, one app

The sidebar switch under **Wayfinder** picks the planner:

- **Rare**: rare tickets, cat food, platinum and legend tickets on your bc.godfat.org seed.
- **Normal**: cat tickets and lucky tickets on your
  [bc-normal-seed-tracking](https://ampuri.github.io/bc-normal-seed-tracking/) seed, for the most blue orbs
  (Cat Capsule power-ups), Li'l Axe Cats worth the same as an orb, and no Dark Catseye given up unless it
  costs more than the orbs you set. Paste the tracker URL, enter your tickets, press **Plan**: each row of
  **Pulls** is one operation (capsule icon, `10` for a 10x pull or `1 ×n` for single pulls, then what comes
  out). Stopping early? Click the last pull you made: the sidebar shows the seed there, a tracker link and the
  tickets left, and **Save progress here** makes it your new start. Command line: `.venv\Scripts\python -m nsplanner --url "<tracker URL>" --cat 100 --lucky 30`.

Both planners show an **improvement factor**: what the plan gets against the same spend pulled straight with
no planning, on average. Normal: blue orbs per cat ticket ÷ 0.474 (9 power-ups out of the Cat Capsule's 19
units). Rare: new-unit value ÷ the average for the same tickets and 11-draws on the best banner open today.

Normal also counts blue orbs as rare tickets (5 orbs = 1 ticket), and its **Lucky tickets** tab (press
**Work it out**) re-plans your cat tickets with 0 to 1.2 lucky tickets per cat ticket: a chart with your
current ratio marked, what you gain over pulling straight, what more lucky tickets would add, and how many
to aim for (on the seeds tried, about 0.9 per cat ticket; beyond that they go unused).

## Use (Rare)

1. Paste your bc.godfat.org tracks URL (with `seed` and `last`) in the sidebar and enter your resources.
2. Press **Fetch banners**, tick what you own under **Owned units**, then press **Plan**.

## Tests

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests -q
```

## Another computer

Copy the folder; the launchers rebuild `.venv` if it came from another machine. `data_cache/settings.json`
holds your seed, resources and owned list: keep it to carry them over, delete it to start fresh.

More: [GUIDE.md](GUIDE.md) for every feature, [PLAN.md](PLAN.md) for the design and build log.
