"""FastAPI application.

No authentication and no permissions: this is a local, reproducible take-home,
and pretending otherwise would add ceremony without adding evidence.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ..clock import Clock, get_clock
from ..config import Settings, load_settings
from ..db.session import build_engine, sessionmaker_for
from ..domain.ownership import OwnershipError
from ..domain.states import TransitionError
from ..services import intake as intake_service
from ..services import metrics as metrics_service
from ..services import requests as request_service
from ..services import routing as routing_service
from ..services import search as search_service
from ..services.intake import IntakeSubmission
from ..services.requests import NewRequest, RequestNotFound, ValidationProblem
from .schemas import ConfirmTarget, CreateRequest, IntakeStart, OwnerRequest, RouteDecision, TransitionRequest


def create_app(
    engine: Engine | None = None,
    settings: Settings | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    clock = clock or get_clock()
    engine = engine or build_engine(settings.db_path)
    factory = sessionmaker_for(engine)

    app = FastAPI(
        title="Halyard",
        version="0.1.0",
        description=(
            "Operational system of record for warm-introduction requests. Every request has an owner, a state and a "
            "next action; candidate paths are evidence about where to investigate, never a claim that an "
            "introduction is available."
        ),
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.engine = engine

    def get_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    @app.exception_handler(RequestNotFound)
    def _not_found(_, exc: RequestNotFound):  # pragma: no cover - exercised through TestClient
        raise HTTPException(status_code=404, detail=f"request '{exc.args[0]}' not found")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "as_of": clock.now(), "database": str(settings.db_path)}

    @app.get("/api/search")
    def search(q: str = Query(""), limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
        return search_service.search(session, q, limit)

    @app.get("/api/accounts/{account_id}")
    def account(account_id: int, session: Session = Depends(get_session)):
        detail = search_service.account_detail(session, account_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"account {account_id} not found")
        return detail

    @app.get("/api/people/{person_id}")
    def person(person_id: int, session: Session = Depends(get_session)):
        detail = search_service.person_detail(session, person_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"person {person_id} not found")
        return detail

    @app.get("/api/requests")
    def list_requests(
        state: str | None = None,
        owner_id: int | None = None,
        account_id: int | None = None,
        origin: str | None = None,
        overdue: bool | None = None,
        stale: bool | None = None,
        ownerless_at_ingest: bool | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        return request_service.list_requests(
            session, settings, clock, state=state, owner_id=owner_id, account_id=account_id, origin=origin,
            overdue=overdue, stale=stale, ownerless_at_ingest=ownerless_at_ingest, query=q, limit=limit, offset=offset,
        )

    @app.post("/api/intake/start", status_code=201)
    def intake_start(body: IntakeStart, session: Session = Depends(get_session)):
        """Persist and own the ask, then return everything known about it.

        The request exists before any parsing or routing happens, so abandoning
        the screen loses nothing.
        """
        try:
            result = intake_service.start_intake(session, IntakeSubmission(**body.model_dump()), settings, clock)
            session.commit()
        except (ValidationProblem, OwnershipError) as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            session.rollback()
            raise
        return result

    @app.get("/api/intake/{request_key}")
    def intake_view(request_key: str, session: Session = Depends(get_session)):
        return _guarded(lambda: intake_service.reintake(session, request_key, settings, clock))

    @app.post("/api/requests/{request_key}/target")
    def confirm_target(request_key: str, body: ConfirmTarget, session: Session = Depends(get_session)):
        try:
            result = routing_service.confirm_target(
                session, request_key, settings, clock, account_id=body.account_id, person_id=body.person_id,
                target_title=body.target_title, actor=body.actor, note=body.note,
            )
            session.commit()
        except RequestNotFound as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=f"request '{request_key}' not found") from exc
        except (ValidationProblem, TransitionError) as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result

    @app.post("/api/requests/{request_key}/route")
    def review_route(request_key: str, body: RouteDecision, session: Session = Depends(get_session)):
        """A human confirms or rejects a candidate path. Nothing else selects a route."""
        try:
            result = routing_service.review_route(
                session, request_key, body.path_id, body.decision, settings, clock,
                actor=body.actor, note=body.note,
            )
            session.commit()
        except RequestNotFound as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=f"request '{request_key}' not found") from exc
        except TransitionError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationProblem as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result

    @app.post("/api/requests", status_code=201)
    def create_request_endpoint(body: CreateRequest, session: Session = Depends(get_session)):
        try:
            request = request_service.create_request(session, NewRequest(**body.model_dump()), settings, clock)
            session.commit()
        except (ValidationProblem, OwnershipError) as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            session.rollback()
            raise
        return request_service.request_detail(session, request.request_id, settings, clock)

    @app.get("/api/requests/{request_key}")
    def request_detail(request_key: str, session: Session = Depends(get_session)):
        return _guarded(lambda: request_service.request_detail(session, request_key, settings, clock))

    @app.post("/api/requests/{request_key}/transition")
    def transition(request_key: str, body: TransitionRequest, session: Session = Depends(get_session)):
        try:
            request_service.transition(
                session, request_key, body.to_state, settings, clock, actor=body.actor, note=body.note,
                route_status=body.route_status, outcome=body.outcome, connector_id=body.connector_id,
                closure_reason=body.closure_reason,
            )
            session.commit()
        except RequestNotFound as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=f"request '{request_key}' not found") from exc
        except TransitionError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationProblem as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return request_service.request_detail(session, request_key, settings, clock)

    @app.patch("/api/requests/{request_key}/owner")
    def set_owner(request_key: str, body: OwnerRequest, session: Session = Depends(get_session)):
        try:
            request_service.set_owner(
                session, request_key, body.operational_owner_id, clock, actor=body.actor, note=body.note
            )
            session.commit()
        except RequestNotFound as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=f"request '{request_key}' not found") from exc
        except ValidationProblem as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return request_service.request_detail(session, request_key, settings, clock)

    @app.get("/api/requests/{request_key}/paths")
    def paths(request_key: str, session: Session = Depends(get_session)):
        return _guarded(lambda: request_service.request_paths(session, request_key, settings, clock))

    @app.get("/api/requests/{request_key}/related")
    def related(request_key: str, session: Session = Depends(get_session)):
        return _guarded(lambda: request_service.related_requests(session, request_key, settings, clock))

    @app.get("/api/metrics/stale")
    def stale(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
        return metrics_service.stale_requests(session, settings, clock, limit)

    @app.get("/api/metrics/connector-load")
    def connector_load(session: Session = Depends(get_session)):
        return metrics_service.connector_load(session, settings, clock)

    @app.get("/api/metrics/leadership")
    def leadership(session: Session = Depends(get_session)):
        return metrics_service.leadership(session, settings, clock)

    return app


def _guarded(fn):
    try:
        return fn()
    except RequestNotFound as exc:
        raise HTTPException(status_code=404, detail=f"request '{exc.args[0]}' not found") from exc
