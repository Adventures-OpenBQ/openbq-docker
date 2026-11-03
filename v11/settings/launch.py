"""v11 entrypoint preserving the pinned ODP app and its configured HTTP hooks."""
import sys
from contextlib import asynccontextmanager
from .config import backend


def main():
    # Configuration fails before importing the heavy provider loader.
    try:
        selected = backend()
        if selected == "postgresql":
            from .config import Config
            Config.read()
    except Exception:
        print("Settings unavailable", file=sys.stderr)
        return 1
    import openbb_platform_api.main as odp
    if selected == "postgresql":
        # ODP's uvicorn module target is shared in this process. Fork/reload workers
        # would import that target without this wrapper, so explicitly refuse them.
        if str(odp.kwargs.get("workers", 1)) != "1" or odp.kwargs.get("reload", False):
            print("Settings requires one worker per container", file=sys.stderr)
            return 1
        if "workers" in odp.kwargs:
            # ODP 2.0.1 leaves unrecognized CLI values as strings; uvicorn
            # compares workers numerically. Only our accepted value is coerced.
            odp.kwargs["workers"] = 1
        from . import lifespan
        previous = odp.app.router.lifespan_context
        @asynccontextmanager
        async def context(app):
            async with lifespan(app, previous):
                yield
        odp.app.router.lifespan_context = context
    odp.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
