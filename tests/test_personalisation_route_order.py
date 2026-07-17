"""Route-order check: /reorder/ must not be shadowed by /{pid}/.

FastAPI matches in declaration order, so declaring /{pid}/ first binds
pid="reorder" and 422s on UUID parsing before the handler ever runs — the
route stays registered and importable, so only resolution order catches it.
Asserts on the route table, not HTTP: no DB, no auth, no client."""
from uuid import uuid4

from starlette.routing import Match

from nova_manager.api.personalisations.router import router


def _first_patch_match(path):
    """The endpoint FastAPI would dispatch a PATCH to — first match wins."""
    scope = {"type": "http", "method": "PATCH", "path": path, "root_path": "", "headers": []}
    for route in router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route.endpoint.__name__
    return None


def test_reorder_not_shadowed_by_pid_route():
    assert _first_patch_match("/reorder/") == "reorder_personalisations"


def test_uuid_path_still_reaches_update():
    assert _first_patch_match(f"/{uuid4()}/") == "update_personalisation"


if __name__ == "__main__":
    test_reorder_not_shadowed_by_pid_route()
    test_uuid_path_still_reaches_update()
    print("ok")
