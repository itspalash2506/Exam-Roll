"""HTTP-level tests for /api/v1/rooms (F02) — the router layer on top of
the Room model/schema work in test_rooms_model.py."""

import pytest

from tests.test_rooms_model import _library_hall


@pytest.mark.asyncio
async def test_create_list_get_room(client):
    res = await client.post("/api/v1/rooms", json=_library_hall())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["capacity"] == 31
    assert body["name"] == "LIBRARY HALL"

    room_id = body["id"]

    res = await client.get("/api/v1/rooms")
    assert any(r["id"] == room_id for r in res.json())

    res = await client.get(f"/api/v1/rooms/{room_id}")
    assert res.status_code == 200
    assert res.json()["capacity"] == 31


@pytest.mark.asyncio
async def test_create_room_rejects_invalid_blocked_seat(client):
    payload = _library_hall(blocked_seats=[{"col": 99, "seat": 1}])
    res = await client.post("/api/v1/rooms", json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_room_rename_keeps_capacity(client):
    res = await client.post("/api/v1/rooms", json=_library_hall(name="Original"))
    room_id = res.json()["id"]

    res = await client.patch(f"/api/v1/rooms/{room_id}", json={"name": "Renamed"})
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Renamed"
    assert body["capacity"] == 31  # untouched fields survive the merge


@pytest.mark.asyncio
async def test_patch_room_rejects_merged_result_that_is_invalid(client):
    """Shrinking seat_columns without updating blocked_seats must be
    rejected — the merged, re-validated result would reference seats that
    no longer exist."""
    res = await client.post("/api/v1/rooms", json=_library_hall())
    room_id = res.json()["id"]

    # Drop to a single 2-seat column; the room's existing blocked_seats
    # reference columns 2 and 3, which would no longer exist.
    res = await client.patch(
        f"/api/v1/rooms/{room_id}",
        json={"seat_columns": [{"label": "Row 1", "seats": 2}]},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_delete_room(client):
    res = await client.post("/api/v1/rooms", json=_library_hall())
    room_id = res.json()["id"]

    res = await client.delete(f"/api/v1/rooms/{room_id}")
    assert res.status_code == 204

    res = await client.get(f"/api/v1/rooms/{room_id}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_generate_rooms_creates_n_identical_rooms(client):
    res = await client.post(
        "/api/v1/rooms/generate",
        json={
            "count": 3,
            "columns": 4,
            "seats_per_column": 10,
            "seats_per_bench": 1,
            "name_pattern": "Room No {n}",
        },
    )
    assert res.status_code == 200, res.text
    rooms = res.json()
    assert len(rooms) == 3
    assert [r["name"] for r in rooms] == ["Room No 1", "Room No 2", "Room No 3"]
    assert all(r["capacity"] == 40 for r in rooms)


@pytest.mark.asyncio
async def test_generate_rooms_requires_placeholder_in_name_pattern(client):
    res = await client.post(
        "/api/v1/rooms/generate",
        json={"count": 2, "columns": 1, "seats_per_column": 5, "name_pattern": "Room"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_rooms_are_isolated_per_org(anon_client, org_a, org_b):
    res = await anon_client.post(
        "/api/v1/rooms", json=_library_hall(), cookies=org_a.cookies
    )
    room_id = res.json()["id"]

    res = await anon_client.get(f"/api/v1/rooms/{room_id}", cookies=org_b.cookies)
    assert res.status_code == 404
