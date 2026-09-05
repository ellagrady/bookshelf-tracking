from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from flask import Flask, flash, redirect, render_template, request, url_for


@dataclass
class Book:
    """The fields displayed and persisted for one physical book."""
    title: str
    book_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    shelf_id: str = ""
    authors: list[str] = field(default_factory=list)
    isbn: str = ""
    publisher: str = ""
    published: str = ""
    cover_url: str = ""
    location: str = "Unsorted"
    notes: str = ""
    source: str = "manual"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Shelf:
    """A persisted shelf category that can exist without any books."""
    name: str
    shelf_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BookRepository(Protocol):
    """Storage contract shared by the in-memory and MongoDB repositories."""
    def list(self) -> list[Book]: ...
    def save(self, book: Book) -> Book: ...
    def delete(self, book: Book) -> None: ...
    def list_shelves(self) -> list[Shelf]: ...
    def save_shelf(self, shelf: Shelf) -> Shelf: ...
    def delete_shelf(self, shelf: Shelf) -> None: ...


class MemoryBookRepository:
    """Small default repository for local development and tests."""
    def __init__(self) -> None:
        self.books: list[Book] = []
        self.shelves: list[Shelf] = [Shelf(name="Unsorted")]

    def list(self) -> list[Book]:
        return list(self.books)

    def save(self, book: Book) -> Book:
        existing = next((item for item in self.books if item.book_id == book.book_id or (item.isbn and item.isbn == book.isbn)), None)
        if existing:
            self.books[self.books.index(existing)] = book
        else:
            self.books.append(book)
        return book

    def delete(self, book: Book) -> None:
        if book in self.books:
            self.books.remove(book)

    def list_shelves(self) -> list[Shelf]:
        return list(self.shelves)

    def save_shelf(self, shelf: Shelf) -> Shelf:
        existing = next((item for item in self.shelves if item.shelf_id == shelf.shelf_id), None)
        if existing:
            self.shelves[self.shelves.index(existing)] = shelf
        else:
            self.shelves.append(shelf)
        return shelf

    def delete_shelf(self, shelf: Shelf) -> None:
        if shelf in self.shelves:
            self.shelves.remove(shelf)


class MongoBookRepository:
    """MongoDB-backed repository used when MONGODB_URI is configured."""
    def __init__(self, uri: str) -> None:
        from pymongo import MongoClient

        database_name = os.getenv("MONGODB_DATABASE", "bookshelf")
        # Keep an unavailable database from blocking Render's health check indefinitely.
        timeout_ms = int(os.getenv("MONGODB_TIMEOUT_MS", "5000"))
        client = MongoClient(
            uri,
            connectTimeoutMS=timeout_ms,
            serverSelectionTimeoutMS=timeout_ms,
            socketTimeoutMS=timeout_ms,
        )
        self.collection = client[database_name]["books"]
        self.shelf_collection = client[database_name]["shelves"]

    def list(self) -> list[Book]:
        return [Book(**{key: value for key, value in row.items() if key != "_id"}) for row in self.collection.find()]

    def save(self, book: Book) -> Book:
        payload = asdict(book)
        self.collection.replace_one({"book_id": book.book_id}, payload, upsert=True)
        return book

    def delete(self, book: Book) -> None:
        self.collection.delete_one({"book_id": book.book_id})

    def list_shelves(self) -> list[Shelf]:
        return [Shelf(**{key: value for key, value in row.items() if key != "_id"}) for row in self.shelf_collection.find()]

    def save_shelf(self, shelf: Shelf) -> Shelf:
        self.shelf_collection.replace_one({"shelf_id": shelf.shelf_id}, asdict(shelf), upsert=True)
        return shelf

    def delete_shelf(self, shelf: Shelf) -> None:
        self.shelf_collection.delete_one({"shelf_id": shelf.shelf_id})


def repository() -> BookRepository:
    """Choose persistent storage only when the deployment supplies MongoDB credentials."""
    uri = os.getenv("MONGODB_URI")
    return MongoBookRepository(uri) if uri else MemoryBookRepository()


def clean_isbn(value: str) -> str:
    """Normalize scanner and user input to digits plus the ISBN-10 check character."""
    return "".join(character for character in value if character.isdigit() or character.upper() == "X").upper()


def cover_url_for_isbn(isbn: str) -> str:
    """Build the Open Library cover URL without making a server-side image request."""
    return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg" if isbn else ""


def lookup_isbn(isbn: str) -> Book:
    """Fetch book metadata from Open Library and map it into the local model."""
    query = urllib.parse.urlencode({"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"})
    with urllib.request.urlopen(f"https://openlibrary.org/api/books?{query}", timeout=8) as response:
        data = json.load(response).get(f"ISBN:{isbn}", {})
    return Book(
        title=data.get("title", "Untitled book"),
        authors=[author.get("name", "") for author in data.get("authors", [])],
        isbn=isbn,
        publisher=(data.get("publishers") or [{}])[0].get("name", ""),
        published=data.get("publish_date", ""),
        cover_url=cover_url_for_isbn(isbn),
        source="openlibrary",
    )

# in case storygraph publishes an API, this is a placeholder for it. 
# async def refresh_from_storygraph() -> list[Book]:
#     endpoint = os.getenv("STORYGRAPH_API_URL")
#     if not endpoint:
#         raise RuntimeError("Set STORYGRAPH_API_URL to enable StoryGraph refresh.")
#     request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
#     with urllib.request.urlopen(request, timeout=10) as response:
#         payload = json.load(response)
#     entries = payload.get("books", payload) if isinstance(payload, dict) else payload
#     return [Book(title=item["title"], authors=item.get("authors", []), isbn=item.get("isbn", ""), source="storygraph")
#             for item in entries if item.get("format", "").lower() not in {"ebook", "audiobook"}]


def create_app(book_repository: BookRepository | None = None) -> Flask:
    """Create the Flask app, injecting a repository for tests when supplied."""
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "shelfmark-development-key")
    books = book_repository or repository()
    shelves = books.list_shelves()
    unsorted = next((shelf for shelf in shelves if shelf.name == "Unsorted"), None)
    if unsorted is None:
        unsorted = books.save_shelf(Shelf(name="Unsorted"))

    # Migrate older books that stored only a shelf name in location.
    shelf_by_name = {shelf.name: shelf for shelf in books.list_shelves()}
    shelf_by_id = {shelf.shelf_id: shelf for shelf in books.list_shelves()}
    for book in books.list():
        shelf_name_value = book.location or "Unsorted"
        shelf = shelf_by_id.get(book.shelf_id) or shelf_by_name.get(shelf_name_value)
        if shelf is None:
            shelf = books.save_shelf(Shelf(name=shelf_name_value, shelf_id=book.shelf_id or str(uuid.uuid4())))
            shelf_by_name[shelf.name] = shelf
            shelf_by_id[shelf.shelf_id] = shelf
        if book.shelf_id != shelf.shelf_id:
            book.shelf_id = shelf.shelf_id
            book.location = shelf.name
            books.save(book)

    def shelf_names() -> list[str]:
        return sorted((shelf.name for shelf in books.list_shelves()), key=lambda name: (name != "Unsorted", name.lower()))

    def shelf_name(book: Book) -> str:
        shelf = next((item for item in books.list_shelves() if item.shelf_id == book.shelf_id), None)
        return shelf.name if shelf else book.location or "Unsorted"

    def shelf_by_route_name(name: str) -> Shelf | None:
        return next((shelf for shelf in books.list_shelves() if shelf.name == name), None)

    def cover_url(book: Book) -> str:
        return book.cover_url or cover_url_for_isbn(book.isbn)

    app.jinja_env.globals["cover_url"] = cover_url
    app.jinja_env.globals["shelf_name"] = shelf_name

    def matching_books(term: str = "") -> list[Book]:
        """Search the collection by the fields users can see or edit."""
        term = term.strip().lower()
        return [book for book in books.list() if not term or term in book.title.lower() or term in " ".join(book.authors).lower() or term in shelf_name(book).lower() or term in book.notes.lower()]

    @app.get("/")
    def index():
        """Render the main collection, optionally filtered by the bookshelf search."""
        term = request.args.get("q", "")
        return render_template("books.html", books=matching_books(term), query=term)

    def shelf_books() -> dict[str, tuple[Shelf, list[Book]]]:
        """Group books by persistent shelf ID while retaining empty shelves."""
        grouped: dict[str, tuple[Shelf, list[Book]]] = {shelf.shelf_id: (shelf, []) for shelf in books.list_shelves()}
        for book in books.list():
            shelf = next((item for item in books.list_shelves() if item.shelf_id == book.shelf_id), unsorted)
            grouped.setdefault(shelf.shelf_id, (shelf, []))[1].append(book)
        return grouped

    @app.get("/shelves")
    def shelves():
        return render_template("shelves.html", shelves=sorted(shelf_books().values(), key=lambda item: (item[0].name != "Unsorted", item[0].name.lower())))

    @app.get("/shelves/search")
    def search_shelves():
        """Return HTML fragments for the Shelves page's in-dialog search."""
        term = request.args.get("q", "").strip().lower()
        grouped = shelf_books().values()
        matching_shelves = [(shelf, shelf_items) for shelf, shelf_items in grouped if term and term in shelf.name.lower()]
        matching_books = [] if matching_shelves else [book for book in books.list() if term and (term in book.title.lower() or term in " ".join(book.authors).lower() or term in shelf_name(book).lower() or term in book.notes.lower())]
        return render_template("shelf_search_results.html", query=request.args.get("q", ""), books=matching_books, shelves=matching_shelves)

    @app.get("/books/search")
    def search_books():
        """Return the same result-card fragment for the Bookshelf search dialog."""
        term = request.args.get("q", "").strip()
        return render_template("shelf_search_results.html", query=term, books=matching_books(term), shelves=[])

    @app.get("/shelves/<path:shelf_name>")
    def shelf_detail(shelf_name: str):
        """Render one shelf and optionally filter books within that shelf."""
        shelf = shelf_by_route_name(shelf_name)
        if shelf is None:
            return "Shelf not found", 404
        term = request.args.get("q", "").strip().lower()
        shelf_items = shelf_books()[shelf.shelf_id][1]
        if term:
            shelf_items = [
                book for book in shelf_items
                if term in book.title.lower()
                or term in " ".join(book.authors).lower()
                or term in book.notes.lower()
            ]
        return render_template("shelf.html", shelf=shelf.name, books=shelf_items, query=request.args.get("q", ""))

    @app.post("/shelves/add")
    def add_shelf():
        """Add a named shelf category without requiring a book first."""
        name = request.form.get("name", "").strip()
        if not name:
            flash("A shelf name is required.", "error")
        else:
            if shelf_by_route_name(name) is None:
                books.save_shelf(Shelf(name=name))
            flash(f"Shelf '{name}' added.", "success")
        return redirect(url_for("shelves"))

    @app.route("/shelves/<path:shelf_name>/edit", methods=["GET", "POST"])
    def edit_shelf(shelf_name: str):
        shelf = shelf_by_route_name(shelf_name)
        if shelf is None:
            return "Shelf not found", 404
        if request.method == "POST":
            new_name = request.form.get("name", "").strip()
            if not new_name:
                flash("A shelf name is required.", "error")
                return render_template("edit_shelf.html", shelf=shelf_name)
            if new_name != shelf_name and shelf_by_route_name(new_name) is not None:
                flash("That shelf already exists.", "error")
                return render_template("edit_shelf.html", shelf=shelf_name)
            for book in books.list():
                if book.shelf_id == shelf.shelf_id:
                    book.shelf_id = shelf.shelf_id
                    book.location = new_name
                    books.save(book)
            shelf.name = new_name
            books.save_shelf(shelf)
            flash(f"Renamed shelf to {new_name}.", "success")
            return redirect(url_for("shelf_detail", shelf_name=new_name))
        return render_template("edit_shelf.html", shelf=shelf_name)

    @app.post("/shelves/<path:shelf_name>/delete")
    def delete_shelf(shelf_name: str):
        shelf = shelf_by_route_name(shelf_name)
        if shelf is None:
            return "Shelf not found", 404
        for book in books.list():
            if book.shelf_id == shelf.shelf_id:
                book.shelf_id = unsorted.shelf_id
                book.location = "Unsorted"
                books.save(book)
        books.delete_shelf(shelf)
        flash(f"Deleted shelf {shelf_name}. Books moved to Unsorted.", "success")
        return redirect(url_for("shelves"))

    @app.route("/books/add", methods=["GET", "POST"])
    def add_book():
        """Render or save a new book from manual or ISBN-assisted entry."""
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            if not title:
                flash("A title is required.", "error")
                return render_template("add_book.html", form=request.form, shelves=shelf_names())
            book = Book(
                title=title,
                authors=[value.strip() for value in request.form.get("authors", "").split(",") if value.strip()],
                isbn=clean_isbn(request.form.get("isbn", "")),
                publisher=request.form.get("publisher", ""),
                published=request.form.get("published", ""),
                cover_url=request.form.get("cover_url", "") or cover_url_for_isbn(clean_isbn(request.form.get("isbn", ""))),
                shelf_id=(shelf_by_route_name(request.form.get("location", "").strip() or "Unsorted") or unsorted).shelf_id,
                location=request.form.get("location", "").strip() or "Unsorted",
                notes=request.form.get("notes", "").strip(),
                source=request.form.get("source", "manual"),
            )
            books.save(book)
            flash(f"Saved {book.title}.", "success")
            return redirect(url_for("index"))
        return render_template("add_book.html", form={}, shelves=shelf_names())

    @app.route("/books/<book_id>", methods=["GET", "POST"])
    def edit_book(book_id: str):
        """Render or save the editable details for one book."""
        book = next((item for item in books.list() if item.book_id == book_id), None)
        if not book:
            return "Book not found", 404
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            if not title:
                flash("A title is required.", "error")
                return render_template("add_book.html", form={**request.form, "book_id": book_id}, shelves=shelf_names(), edit=True)
            book.title = title
            book.authors = [value.strip() for value in request.form.get("authors", "").split(",") if value.strip()]
            book.isbn = clean_isbn(request.form.get("isbn", ""))
            book.cover_url = cover_url_for_isbn(book.isbn)
            selected_shelf = shelf_by_route_name(request.form.get("location", "").strip() or "Unsorted") or unsorted
            book.shelf_id = selected_shelf.shelf_id
            book.location = selected_shelf.name
            book.notes = request.form.get("notes", "").strip()
            books.save(book)
            flash(f"Updated {book.title}.", "success")
            return redirect(url_for("index"))
        return render_template("add_book.html", form={"book_id": book.book_id, "title": book.title, "authors": ", ".join(book.authors), "isbn": book.isbn, "location": shelf_name(book), "notes": book.notes, "publisher": book.publisher, "published": book.published, "cover_url": book.cover_url, "source": book.source}, shelves=shelf_names(), edit=True)

    @app.post("/books/<book_id>/delete")
    def delete_book(book_id: str):
        """Delete a book after the edit page's client-side confirmation."""
        book = next((item for item in books.list() if item.book_id == book_id), None)
        if not book:
            return "Book not found", 404
        books.delete(book)
        flash(f"Deleted {book.title}.", "success")
        return redirect(url_for("index"))

    @app.route("/lookup", methods=["GET", "POST"])
    def lookup():
        """Show the ISBN lookup form or turn lookup metadata into an editable book form."""
        if request.method == "GET":
            return render_template("lookup.html")
        isbn = clean_isbn(request.form.get("isbn", ""))
        if not isbn:
            flash("Enter an ISBN to look it up.", "error")
            return redirect(url_for("index"))
        try:
            book = lookup_isbn(isbn)
        except Exception as error:
            flash(f"Lookup failed: {error}", "error")
            return redirect(url_for("index"))
        flash("Metadata found. Add its shelf before saving.", "success")
        return render_template("add_book.html", form={"title": book.title, "authors": ", ".join(book.authors), "isbn": book.isbn, "location": book.location, "publisher": book.publisher, "published": book.published, "cover_url": book.cover_url, "source": book.source, "notes": book.notes}, shelves=shelf_names())

    # placeholder should storygraph ever publish an API for this, the following route could be uncommented to allow users to refresh their books from storygraph.
    # @app.post("/refresh")
    # def refresh():
    #     try:
    #         import asyncio
    #         refreshed = asyncio.run(refresh_from_storygraph())
    #         for book in refreshed:
    #             books.save(book)
    #         flash("StoryGraph books refreshed.", "success")
    #     except Exception as error:
    #         flash(str(error), "error")
    #     return redirect(url_for("index"))

    return app


app = create_app()


def main() -> None:
    """Run the development server; Render uses Gunicorn's app object instead."""
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=True,
    )


if __name__ == "__main__":
    main()