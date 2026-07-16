"""Reorder logic check: top-first → highest priority, and permutation guard.

Uses a mocked session (the two-phase negative-parking is a DB-constraint
mechanic; what can silently break is the priority arithmetic and the
exact-permutation guard, which this locks down)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from nova_manager.components.personalisations.crud import PersonalisationsCRUD


def _crud_with(rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = rows
    crud = PersonalisationsCRUD.__new__(PersonalisationsCRUD)  # skip BaseCRUD __init__
    crud.db = db
    return crud


def test_reorder_top_gets_highest_priority():
    rows = [SimpleNamespace(pid=p, priority=0, reassign=False) for p in ("a", "b", "c")]
    crud = _crud_with(rows)
    result = crud.reorder_personalisations("exp", ["b", "a", "c"])  # top-first
    prio = {r.pid: r.priority for r in rows}
    assert prio == {"b": 3, "a": 2, "c": 1}          # top (b) = highest int
    assert [r.pid for r in result] == ["b", "a", "c"]
    assert all(r.reassign for r in rows)             # order changed → reassign


def test_reorder_rejects_non_permutation():
    rows = [SimpleNamespace(pid=p, priority=0, reassign=False) for p in ("a", "b")]
    assert _crud_with(rows).reorder_personalisations("exp", ["a"]) is None            # missing b
    assert _crud_with(rows).reorder_personalisations("exp", ["a", "b", "x"]) is None  # extra x


if __name__ == "__main__":
    test_reorder_top_gets_highest_priority()
    test_reorder_rejects_non_permutation()
    print("ok")
