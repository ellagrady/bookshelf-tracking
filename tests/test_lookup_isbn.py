import json
import re

from bookshelf_tracking import Book, MemoryBookRepository, Shelf, create_app, lookup_isbn


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_lookup_isbn_uses_current_openlibrary_isbn_endpoint(monkeypatch):
    isbn = "9780140328721"
    payload = {
        "title": "Fantastic Mr. Fox",
        "authors": [{"key": "/authors/OL34184A"}],
        "publishers": ["Puffin"],
        "publish_date": "October 1, 1988",
    }

    def fake_urlopen(request, timeout=8):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url == f"https://openlibrary.org/isbn/{isbn}.json":
            return FakeResponse(payload)
        if url == "https://openlibrary.org/authors/OL34184A.json":
            return FakeResponse({"name": "Roald Dahl"})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("bookshelf_tracking.urllib.request.urlopen", fake_urlopen)

    book = lookup_isbn(isbn)

    assert book.title == "Fantastic Mr. Fox"
    assert book.authors == ["Roald Dahl"]
    assert book.publisher == "Puffin"
    assert book.published == "October 1, 1988"
    assert book.isbn == isbn


def test_lookup_isbn_falls_back_to_search_results_for_missing_author_data(monkeypatch):
    isbn = "9780525556572"
    isbn_payload = {
        "title": "Everything Is Tuberculosis",
        "authors": None,
        "publishers": ["Penguin Random House"],
        "publish_date": "2025",
    }
    search_payload = {
        "docs": [{
            "title": "Everything Is Tuberculosis",
            "author_name": ["John Green"],
            "author_key": ["OL5046634A"],
        }]
    }

    def fake_urlopen(request, timeout=8):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url == f"https://openlibrary.org/isbn/{isbn}.json":
            return FakeResponse(isbn_payload)
        if url == f"https://openlibrary.org/search.json?q={isbn}":
            return FakeResponse(search_payload)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("bookshelf_tracking.urllib.request.urlopen", fake_urlopen)

    book = lookup_isbn(isbn)

    assert book.authors == ["John Green"]
    assert book.publisher == "Penguin Random House"
    assert book.isbn == isbn


def test_books_pages_sort_by_author_last_name():
    repo = MemoryBookRepository()
    shelf = Shelf(name="Classic Fiction")
    repo.save_shelf(shelf)

    repo.save(Book(title="The Last Book", authors=["John Steinbeck"], shelf_id=shelf.shelf_id, location=shelf.name))
    repo.save(Book(title="A Quiet Place", authors=["Zoe Adams"], shelf_id=shelf.shelf_id, location=shelf.name))
    repo.save(Book(title="Another Story", authors=["Jane Austen"], shelf_id=shelf.shelf_id, location=shelf.name))

    app = create_app(repo)
    with app.test_client() as client:
        all_books_response = client.get("/")
        all_titles = re.findall(r"<h2>(.*?)</h2>", all_books_response.get_data(as_text=True))
        assert all_titles.index("A Quiet Place") < all_titles.index("Another Story") < all_titles.index("The Last Book")

        shelf_response = client.get("/shelves/Classic%20Fiction")
        shelf_titles = re.findall(r"<h2>(.*?)</h2>", shelf_response.get_data(as_text=True))
        assert shelf_titles.index("A Quiet Place") < shelf_titles.index("Another Story") < shelf_titles.index("The Last Book")
