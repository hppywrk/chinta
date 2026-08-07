"""Functional tests for the notebook service (via gateway and directly)."""


def test_create_and_list_notes(notebook):
    """Create a note directly against the notebook service, then list."""
    resp = notebook.post(
        "/notes",
        json={"title": "Test Note", "body": "Hello world", "tags": ["test", "demo"]},
    )
    assert resp.status_code == 201
    note = resp.json()
    assert note["title"] == "Test Note"
    assert note["body"] == "Hello world"
    assert sorted(note["tags"]) == ["demo", "test"]
    note_id = note["id"]

    resp = notebook.get("/notes")
    assert resp.status_code == 200
    notes = resp.json()
    assert any(n["id"] == note_id for n in notes)

    # Clean up
    resp = notebook.delete(f"/notes/{note_id}")
    assert resp.status_code == 204


def test_get_note_by_id(notebook):
    resp = notebook.post("/notes", json={"title": "Lookup", "body": "By ID"})
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    resp = notebook.get(f"/notes/{note_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Lookup"

    notebook.delete(f"/notes/{note_id}")


def test_filter_by_tag(notebook):
    resp = notebook.post(
        "/notes",
        json={"title": "Tagged", "body": "Filter me", "tags": ["special"]},
    )
    note_id = resp.json()["id"]

    resp = notebook.get("/notes", params={"tag": "special"})
    assert resp.status_code == 200
    assert any(n["id"] == note_id for n in resp.json())

    notebook.delete(f"/notes/{note_id}")


def test_delete_nonexistent_note(notebook):
    resp = notebook.delete("/notes/999999")
    assert resp.status_code == 404


def test_gateway_proxies_notes(gateway):
    """Create a note via the gateway /api/notes proxy."""
    resp = gateway.post(
        "/api/notes",
        json={"title": "Via Gateway", "body": "Proxied", "tags": ["gw"]},
    )
    assert resp.status_code == 201
    note = resp.json()
    assert note["title"] == "Via Gateway"
    note_id = note["id"]

    resp = gateway.get("/api/notes")
    assert resp.status_code == 200
    assert any(n["id"] == note_id for n in resp.json())

    gateway.delete(f"/api/notes/{note_id}")
