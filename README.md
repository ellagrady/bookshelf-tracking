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

On the Books page, tap **Use camera to scan**, allow camera access, and point the
rear camera at the book's ISBN barcode. The scan fills the ISBN field and sends
it to Open Library. If camera access is unavailable, the ISBN can still be
entered manually.

The app uses an in-memory repository by default, so it is usable immediately. To persist books in MongoDB, set `MONGODB_URI` and optionally `MONGODB_DATABASE` before launching.

For MongoDB Atlas, add Render's connection source in Atlas Network Access. For
an initial test, `0.0.0.0/0` allows connections from Render, but use stronger
network restrictions where possible. Set `MONGODB_TIMEOUT_MS` to change the
database connection timeout; it defaults to 5 seconds.

## Features

- Add books manually or look up ISBN metadata through Open Library.
- Use a hardware scanner that types into the ISBN field, then press Enter.
- Search by title, author, or shelf location.
- Group books by shelf.
- Unless Storygraph comes out with an API, not functional~~Refresh physical books from a compatible `storygraph-api` service by setting `STORYGRAPH_API_URL`.~~

~~StoryGraph integrations are configured through an adapter endpoint because deployments and response shapes can vary. The expected response is either a list of books or `{ "books": [...] }`, with each item containing `title`, optional `authors`, `isbn`, and `format`.~~