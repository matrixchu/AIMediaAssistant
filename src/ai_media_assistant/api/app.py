"""FastAPI application: REST API + agent chat + static dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent.memory import AgentMemoryStore
from ..agent.runner import AgentRunner
from ..database import init_db, session_scope
from ..database import repositories as repo
from ..services.download_service import DownloadService
from ..services.follow_service import FollowService
from ..services.recommendation_service import RecommendationService
from ..services.scheduler_service import get_scheduler_manager
from ..services.search_service import SearchService
from ..shared.config import get_settings
from ..shared.errors import AIMediaError, ResourceNotFoundError
from ..shared.logging import get_logger, setup_logging
from ..shared.schemas import AgentRequest, AgentResponse, SearchQuery

logger = get_logger(__name__)


# Request bodies are defined at module level so FastAPI can resolve them as JSON
# bodies (with `from __future__ import annotations`, locally-scoped models would
# be misread as query parameters).
class DownloadReq(BaseModel):
    resource_id: int
    confirm: bool = False
    save_path: str | None = None


class FollowReq(BaseModel):
    title: str
    season: int | None = None
    quality: str | None = None

_WEB_DIR = Path(__file__).resolve().parents[1] / "web"

# Background task handle
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    init_db()
    scheduler = get_scheduler_manager()
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("API started")
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Media Assistant", version="0.1.0", lifespan=lifespan)

    runner = AgentRunner()
    search = SearchService()
    download = DownloadService()
    follow = FollowService()
    recommend = RecommendationService()
    memory = AgentMemoryStore()

    # ---------------- Agent ----------------
    @app.post("/api/agent/chat", response_model=AgentResponse)
    def agent_chat(req: AgentRequest) -> AgentResponse:
        return runner.run(req)

    # ---------------- Search ----------------
    @app.get("/api/search")
    def api_search(
        keyword: str = "",
        category: str = "",
        resolution: str = "",
        quality: str = "",
        min_seeders: int = 0,
        min_size_gb: float = 0.0,
        max_size_gb: float = 0.0,
    ):
        query = SearchQuery(
            keyword=keyword,
            category=category or None,
            resolution=resolution or None,
            quality=quality or None,
            min_seeders=min_seeders if min_seeders > 0 else None,
            min_size_gb=min_size_gb if min_size_gb > 0 else None,
            max_size_gb=max_size_gb if max_size_gb > 0 else None,
        )
        return search.search(query).model_dump()

    # ---------------- Downloads ----------------
    @app.post("/api/download")
    def api_download(req: DownloadReq):
        try:
            return download.download(
                req.resource_id,
                confirm=req.confirm,
                save_path=req.save_path,
            ).model_dump()
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AIMediaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/downloads")
    def api_downloads():
        return [t.model_dump() for t in download.list_tasks()]

    @app.get("/api/downloads/{task_id}")
    def api_download_status(task_id: int):
        task = download.refresh(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return task.model_dump()

    # ---------------- Follow ----------------
    @app.post("/api/follow")
    def api_follow(req: FollowReq):
        return follow.follow_show(req.title, season=req.season, quality=req.quality)

    @app.get("/api/subscriptions")
    def api_subscriptions():
        return [s.model_dump() for s in follow.list_subscriptions()]

    @app.get("/api/subscriptions/{sub_id}/episodes")
    def api_episodes(sub_id: int):
        return [e.model_dump() for e in follow.list_episodes(sub_id)]

    # ---------------- Recommendations ----------------
    @app.get("/api/recommendations")
    def api_recommend(query: str = ""):
        return [r.model_dump() for r in recommend.recommend(query)]

    # ---------------- Scheduler ----------------
    @app.get("/api/scheduler/status")
    def api_scheduler_status():
        return app.state.scheduler.snapshot()

    @app.post("/api/scheduler/jobs/{job_name}/pause")
    def api_scheduler_pause(job_name: str):
        try:
            return app.state.scheduler.pause_job(job_name).__dict__
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/scheduler/jobs/{job_name}/resume")
    def api_scheduler_resume(job_name: str):
        try:
            return app.state.scheduler.resume_job(job_name).__dict__
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/scheduler/jobs/{job_name}/restart")
    def api_scheduler_restart(job_name: str):
        try:
            return app.state.scheduler.restart_job(job_name).__dict__
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/scheduler/jobs/{job_name}/run")
    def api_scheduler_run_now(job_name: str):
        try:
            return app.state.scheduler.run_job_now(job_name).__dict__
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ---------------- Memory & trace ----------------
    @app.get("/api/memory")
    def api_memory():
        return memory.all()

    @app.get("/api/tasks/{task_id}/trace")
    def api_trace(task_id: int):
        with session_scope() as session:
            return [
                {
                    "step_name": log.step_name,
                    "tool_name": log.tool_name,
                    "request": log.request_data,
                    "response": log.response_data,
                    "time": log.created_time.isoformat() if log.created_time else None,
                }
                for log in repo.list_execution_logs(session, task_id)
            ]

    # ---------------- Health & dashboard ----------------
    @app.get("/health")
    def health():
        return {"status": "ok", "scheduler_running": app.state.scheduler.is_running()}

    @app.get("/")
    def index():
        return FileResponse(_WEB_DIR / "index.html")

    if _WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=_WEB_DIR), name="static")

    return app


app = create_app()
