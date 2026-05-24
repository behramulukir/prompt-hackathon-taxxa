"""HTTP sidecar package — wraps the GraphRAG pipeline for the Next.js frontend.

The Next.js app proxies ``/api/ask`` and ``/api/excerpt`` to this service via
``AGENT_SIDECAR_URL`` (default ``http://localhost:8000``). Events are framed
as SSE so the UI can animate stage-by-stage; the event types are defined in
``lex-atlas-frontend/lib/types.ts`` (mirrored here in ``events.py``).

Run with::

    uvicorn src.api.server:app --reload --port 8000
"""
