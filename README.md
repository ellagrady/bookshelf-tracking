# Bookshelf Tracking

A personal, mobile-friendly Python app for tracking which shelf holds each book.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
bookshelf-tracking
```

To run directly from a checkout instead, use `python src/bookshelf_tracking.py`.

## Use it on an iPhone

The Flask server must be reachable from the phone over HTTPS for camera access.
For local development, use a secure tunnel such as `ngrok` or deploy the app to
a host with HTTPS. Then open the site in Safari and choose **Share → Add to
Home Screen**. The installed shortcut opens Shelfmark in its own app-like
window.

To bind Flask for a tunnel or local-network test, set `FLASK_HOST` and
optionally `FLASK_PORT`, for example:

```bash
FLASK_HOST=0.0.0.0 FLASK_PORT=5000 python src/bookshelf_tracking.py
```

For Render, use a Gunicorn start command that listens on Render's assigned
port:

```bash
gunicorn --chdir src --bind 0.0.0.0:$PORT bookshelf_tracking:app
```

From the **+ Add book** menu, choose manual entry, ISBN lookup, or camera scan.
Allow camera access and point the rear camera at the book's ISBN barcode. The
scan fills the ISBN field; submit it to Open Library to retrieve metadata. If
camera access is unavailable, the ISBN can still be entered manually.

The app uses an in-memory repository by default, so it is usable immediately. To persist books in MongoDB, set `MONGODB_URI` and optionally `MONGODB_DATABASE` before launching.

For MongoDB Atlas, add Render's connection source in Atlas Network Access. For
an initial test, `0.0.0.0/0` allows connections from Render, but use stronger
network restrictions where possible. Set `MONGODB_TIMEOUT_MS` to change the
database connection timeout; it defaults to 5 seconds.

## Features

- Add books manually or look up ISBN metadata through Open Library.
- Scan ISBN barcodes with a phone camera or use a hardware scanner.
- Display Open Library cover images for books with ISBNs.
- Edit book title, author, ISBN, shelf, and notes after saving.
- Delete books with confirmation.
- Create shelf categories, including shelves with no books yet.
- Rename or delete shelves; deleting a shelf moves its books to `Unsorted` instead of deleting them.
- Browse shelves and open each shelf as its own page.
- Search the bookshelf, shelves, and books within an individual shelf.
- Store books in memory by default or persist them in MongoDB.
- Install the app as a mobile home-screen shortcut with a PWA manifest and service worker.

## MongoDB and Render

The app uses the in-memory repository unless `MONGODB_URI` is set. For MongoDB
Atlas, configure these environment variables in Render:

```text
MONGODB_URI=mongodb+srv://USERNAME:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=bookshelf
MONGODB_TIMEOUT_MS=5000
FLASK_SECRET_KEY=replace-with-a-secret-value
```

URL-encode special characters in the MongoDB password. In Atlas, allow the
Render service to connect through **Network Access** and grant the database
user read/write access. `0.0.0.0/0` can be used temporarily for testing, but
restrict access where possible.

For a Render Web Service, use:

```text
Build command: pip install -e . gunicorn
Start command: gunicorn --chdir src --bind 0.0.0.0:$PORT bookshelf_tracking:app
```

The Render service provides HTTPS, which is required for camera scanning.

## StoryGraph

StoryGraph import is not currently enabled. The previously explored
`storygraph-api` package scrapes public StoryGraph pages, requires a user cookie,
and does not provide all of the ISBN and cover data this app needs. Books can
instead be added through Open Library lookup or manual entry.