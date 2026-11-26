import asyncio
import base64
import hmac
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import gabarito, views
from .alerts import CanonicalAlert, InvalidAlert, parse_webhook
from .campaign import CampaignConflict, CampaignInvalid, CampaignNotFound
from .demo import DemoConflict, DemoDisabled, DemoUnknownFault
from .events import GLOBAL_TOPIC, encode
from .flags import FlagError
from .service import DeleteBusy, DeleteNotFound, ReplayConflict, ReplayNotFound
from .store import STATE_FILTERS

MAX_LIMIT = 200
MAX_WEBHOOK_BYTES = 1_000_000
HEARTBEAT_S = 15


class NewDemoIncident(BaseModel):
    kind: str = Field(min_length=1, max_length=40)


class NewCampaign(BaseModel):
    per_fault: int = Field(ge=1, le=30)


class CampaignChange(BaseModel):
    state: str


class NewInvestigation(BaseModel):
    alert_name: str = Field(min_length=1, max_length=120)
    service: str = Field(min_length=1, max_length=80)
    starts_at: datetime


def encode_cursor(row):
    raw = "%s|%s" % (row["received_at"].isoformat(), row["id"])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value):
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        stamp, identifier = raw.split("|", 1)
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None or not identifier:
            raise ValueError
        return moment, identifier
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "cursor inválido")


def authorized(request, token):
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(value.strip().encode(), token.encode())


def create_app(service, store, hub, settings, lifespan=None, demo=None, narrator_on=False, runner=None, campaigns=None):
    app = FastAPI(title="AnomalyGuard", version="0.2.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"status": "ok", "demo_mode": settings.demo_mode and demo is not None, "narrator": narrator_on}

    def demo_call(function):
        if demo is None:
            raise HTTPException(404, "o modo demonstração está desligado")
        try:
            return function()
        except DemoDisabled as e:
            raise HTTPException(404, str(e))
        except DemoConflict as e:
            raise HTTPException(409, str(e))
        except DemoUnknownFault as e:
            raise HTTPException(422, str(e))
        except FlagError as e:
            raise HTTPException(502, str(e))

    @app.post("/api/demo/incidents", status_code=202)
    def start_demo_incident(body: NewDemoIncident):
        return demo_call(lambda: demo.start(body.kind))

    @app.get("/api/demo/faults")
    def demo_faults():
        return {"faults": demo_call(lambda: demo.options())}

    @app.get("/api/demo/incidents/current")
    def current_demo_incident():
        return {"incident": demo_call(lambda: demo.current())}

    @app.delete("/api/demo/incidents/current")
    def stop_demo_incident():
        return demo_call(lambda: demo.stop())

    def campaign_call(function):
        if demo is None or campaigns is None:
            raise HTTPException(404, "o modo demonstração está desligado")
        try:
            return function()
        except DemoDisabled as e:
            raise HTTPException(404, str(e))
        except CampaignNotFound as e:
            raise HTTPException(404, str(e))
        except (CampaignConflict, DemoConflict) as e:
            raise HTTPException(409, str(e))
        except CampaignInvalid as e:
            raise HTTPException(422, str(e))

    @app.get("/api/accuracy")
    def accuracy_report():
        if campaigns is None:
            raise HTTPException(404, "o modo demonstração está desligado")
        return campaigns.report()

    @app.post("/api/campaign", status_code=202)
    def start_campaign(body: NewCampaign):
        return campaign_call(lambda: campaigns.start(body.per_fault))

    @app.patch("/api/campaign")
    def change_campaign(body: CampaignChange):
        if body.state not in ("paused", "running"):
            raise HTTPException(422, "state precisa ser paused ou running")
        return campaign_call(lambda: campaigns.pause() if body.state == "paused" else campaigns.resume())

    @app.delete("/api/campaign")
    def stop_campaign():
        return campaign_call(lambda: campaigns.stop())

    @app.post("/webhooks/alertmanager", status_code=202)
    async def alertmanager(request: Request):
        if not authorized(request, settings.webhook_token):
            raise HTTPException(401, "token inválido")
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "corpo grande demais")
        try:
            alerts = parse_webhook(await request.json())
        except (InvalidAlert, ValueError) as e:
            raise HTTPException(400, str(e))
        outcomes = await run_in_threadpool(lambda: [service.ingest(a) for a in alerts])
        return {"received": len(alerts), "outcomes": [{"action": o.action, "id": o.investigation_id} for o in outcomes]}

    @app.post("/api/investigations", status_code=202)
    def create(body: NewInvestigation):
        if body.starts_at.tzinfo is None:
            raise HTTPException(422, "starts_at precisa ter fuso horário, por exemplo 2026-11-21T14:03:10Z")
        starts_at = body.starts_at.astimezone(timezone.utc)
        alert = CanonicalAlert("manual-" + uuid.uuid4().hex[:12], "firing", body.alert_name, body.service, {"alertname": body.alert_name, "service": body.service},
                               {}, starts_at, None)
        outcome = service.ingest(alert)
        return {"id": outcome.investigation_id, "action": outcome.action}

    @app.get("/api/investigations")
    def list_investigations(limit: int = Query(50, ge=1, le=MAX_LIMIT), cursor: Optional[str] = None, state: Optional[str] = None,
                            service: Optional[str] = Query(None, max_length=80)):
        if state is not None and state not in STATE_FILTERS:
            raise HTTPException(400, "state precisa ser um de: %s" % ", ".join(STATE_FILTERS))
        position = decode_cursor(cursor) if cursor else None
        rows = store.list(limit + 1, position, state, service)
        more = len(rows) > limit
        rows = rows[:limit]
        truths = store.ground_truths([r["id"] for r in rows])
        return {"items": [views.summary(r, truths.get(r["id"])) for r in rows], "next_cursor": encode_cursor(rows[-1]) if more else None,
                "total": store.count(state, service)}

    @app.get("/api/evaluation")
    def evaluation():
        cases = []
        for row, truth in store.labeled():
            view = gabarito.evaluate(truth, row)
            top = row["suspects"][0] if row["suspects"] else None
            cases.append(dict(gabarito.compact(view), id=row["id"], source=truth["source"], fault_kind=truth["fault_kind"], received_at=views.to_iso(row["received_at"]),
                              top_suspect={"service": top["service"], "share": top["share"]} if top else None))
        return {"summary": gabarito.summarize(cases), "cases": cases}

    @app.get("/api/investigations/facets")
    def facets():
        return {"services": store.services(), "states": {name: store.count(name) for name in STATE_FILTERS}}

    @app.get("/api/investigations/{identifier}")
    def get_investigation(identifier: str):
        detail = service.detail(identifier)
        if detail is None:
            raise HTTPException(404, "investigação não encontrada")
        return detail

    @app.delete("/api/investigations/{identifier}")
    def delete_investigation(identifier: str):
        try:
            return service.delete(identifier)
        except DeleteNotFound as e:
            raise HTTPException(404, str(e))
        except DeleteBusy as e:
            raise HTTPException(409, str(e))

    @app.delete("/api/investigations")
    def delete_all_investigations():
        return service.delete_all()

    @app.post("/api/investigations/{identifier}/replay", status_code=202)
    def replay(identifier: str):
        try:
            new_id = service.open_replay(identifier)
        except ReplayNotFound as e:
            raise HTTPException(404, str(e))
        except ReplayConflict as e:
            raise HTTPException(409, str(e))
        runner.submit_replay(new_id, identifier)
        return {"id": new_id, "replay_of": identifier}

    def stream(request, topic, first=None):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        subscription = hub.subscribe(topic, lambda event: loop.call_soon_threadsafe(queue.put_nowait, event))

        async def generate():
            try:
                yield "retry: 3000\n\n"
                if first is not None:
                    yield encode(first)
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": heartbeat\n\n"
                        continue
                    yield encode(event)
            finally:
                subscription.close()

        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/events")
    async def global_events(request: Request):
        return stream(request, GLOBAL_TOPIC)

    @app.get("/api/investigations/{identifier}/events")
    async def investigation_events(identifier: str, request: Request):
        detail = await run_in_threadpool(service.detail, identifier)
        if detail is None:
            raise HTTPException(404, "investigação não encontrada")
        return stream(request, identifier, hub.make("snapshot", detail))

    return app
