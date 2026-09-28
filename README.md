# Wayfinder

Searches all possibilities to deliver optimal BCEN seed navigation.

A Battle Cats (English version) pull planner: from your bc.godfat.org seed it finds the best way to spend
rare tickets, cat food, platinum and legend tickets. Needs Python 3.10 or newer and an internet connection.

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

## Use

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
