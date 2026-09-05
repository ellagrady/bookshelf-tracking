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
    title: str
    book_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    authors: list[str] = field(default_factory=list)
    isbn: str = ""
    publisher: str = ""
    published: str = ""
    cover_url: str = ""
    location: str = "Unsorted"
    notes: str = ""
    source: str = "manual"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BookRepository(Protocol):
    def list(self) -> list[Book]: ...
    def save(self, book: Book) -> Book: ...
    def delete(self, book: Book) -> None: ...


class MemoryBookRepository:
    def __init__(self) -> None:
        self.books: list[Book] = []

    def list(self) -> list[Book]:
        return list(self.books)

    def save(self, book: Book) -> Book:
        existing = next((item for item in self.books if item.isbn and item.isbn == book.isbn), None)
        if existing:
            self.books[self.books.index(existing)] = book
        else:
            self.books.append(book)
        return book

    def delete(self, book: Book) -> None:
        if book in self.books:
            self.books.remove(book)


class MongoBookRepository:
    def __init__(self, uri: str) -> None:
        from pymongo import MongoClient

        database_name = os.getenv("MONGODB_DATABASE", "bookshelf")
        timeout_ms = int(os.getenv("MONGODB_TIMEOUT_MS", "5000"))
        client = MongoClient(
            uri,
            connectTimeoutMS=timeout_ms,
            serverSelectionTimeoutMS=timeout_ms,
            socketTimeoutMS=timeout_ms,
        )
        self.collection = client[database_name]["books"]

    def list(self) -> list[Book]:
        return [Book(**{key: value for key, value in row.items() if key != "_id"}) for row in self.collection.find()]

    def save(self, book: Book) -> Book:
        payload = asdict(book)
        if book.isbn:
            self.collection.replace_one({"isbn": book.isbn}, payload, upsert=True)
        else:
            self.collection.insert_one(payload)
        return book

    def delete(self, book: Book) -> None:
        self.collection.delete_one({"book_id": book.book_id})


def repository() -> BookRepository:
    uri = os.getenv("MONGODB_URI")
    return MongoBookRepository(uri) if uri else MemoryBookRepository()


def clean_isbn(value: str) -> str:
    return "".join(character for character in value if character.isdigit() or character.upper() == "X").upper()


def cover_url_for_isbn(isbn: str) -> str:
    return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg" if isbn else ""


def lookup_isbn(isbn: str) -> Book:
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
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "shelfmark-development-key")
    books = book_repository or repository()
    shelf_categories = {"Unsorted"}

    def shelf_names() -> list[str]:
        shelf_categories.update(book.location for book in books.list() if book.location)
        return sorted(shelf_categories, key=lambda shelf: (shelf != "Unsorted", shelf.lower()))

    def cover_url(book: Book) -> str:
        return book.cover_url or cover_url_for_isbn(book.isbn)

    app.jinja_env.globals["cover_url"] = cover_url

    def matching_books(term: str = "") -> list[Book]:
        term = term.strip().lower()
        return [book for book in books.list() if not term or term in book.title.lower() or term in " ".join(book.authors).lower() or term in book.location.lower() or term in book.notes.lower()]

    @app.get("/")
    def index():
        term = request.args.get("q", "")
        return render_template("books.html", books=matching_books(term), query=term)

    def shelf_books() -> dict[str, list[Book]]:
        grouped: dict[str, list[Book]] = {shelf: [] for shelf in shelf_names()}
        for book in books.list():
            grouped.setdefault(book.location or "Unsorted", []).append(book)
        return grouped

    @app.get("/shelves")
    def shelves():
        return render_template("shelves.html", shelves=sorted(shelf_books().items()))

    @app.get("/shelves/search")
    def search_shelves():
        term = request.args.get("q", "").strip().lower()
        grouped = shelf_books()
        matching_shelves = [(shelf, shelf_items) for shelf, shelf_items in grouped.items() if term and term in shelf.lower()]
        matching_books = [] if matching_shelves else [book for book in books.list() if term and (term in book.title.lower() or term in " ".join(book.authors).lower() or term in book.location.lower() or term in book.notes.lower())]
        return render_template("shelf_search_results.html", query=request.args.get("q", ""), books=matching_books, shelves=matching_shelves)

    @app.get("/books/search")
    def search_books():
        term = request.args.get("q", "").strip()
        return render_template("shelf_search_results.html", query=term, books=matching_books(term), shelves=[])

    @app.get("/shelves/<path:shelf_name>")
    def shelf_detail(shelf_name: str):
        grouped = shelf_books()
        if shelf_name not in grouped:
            return "Shelf not found", 404
        term = request.args.get("q", "").strip().lower()
        shelf_items = grouped[shelf_name]
        if term:
            shelf_items = [
                book for book in shelf_items
                if term in book.title.lower()
                or term in " ".join(book.authors).lower()
                or term in book.notes.lower()
            ]
        return render_template("shelf.html", shelf=shelf_name, books=shelf_items, query=request.args.get("q", ""))

    @app.post("/shelves/add")
    def add_shelf():
        name = request.form.get("name", "").strip()
        if not name:
            flash("A shelf name is required.", "error")
        else:
            shelf_categories.add(name)
            flash(f"Shelf '{name}' added.", "success")
        return redirect(url_for("shelves"))

    @app.route("/books/add", methods=["GET", "POST"])
    def add_book():
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
            book.location = request.form.get("location", "").strip() or "Unsorted"
            book.notes = request.form.get("notes", "").strip()
            books.save(book)
            flash(f"Updated {book.title}.", "success")
            return redirect(url_for("index"))
        return render_template("add_book.html", form={"book_id": book.book_id, "title": book.title, "authors": ", ".join(book.authors), "isbn": book.isbn, "location": book.location, "notes": book.notes, "publisher": book.publisher, "published": book.published, "cover_url": book.cover_url, "source": book.source}, shelves=shelf_names(), edit=True)

    @app.post("/books/<book_id>/delete")
    def delete_book(book_id: str):
        book = next((item for item in books.list() if item.book_id == book_id), None)
        if not book:
            return "Book not found", 404
        books.delete(book)
        flash(f"Deleted {book.title}.", "success")
        return redirect(url_for("index"))

    @app.route("/lookup", methods=["GET", "POST"])
    def lookup():
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
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=True,
    )


if __name__ == "__main__":
    main()