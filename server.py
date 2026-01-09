from __future__ import annotations

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import UUID, uuid4
import json
import datetime
import dotenv
import jsonschema
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.requests import Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, delete, func, select, cast, Numeric, Boolean, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

dotenv.load_dotenv()

from datamodel import (
    Attachment,
    AttachmentOut,
    Edge,
    EdgeCreate,
    EdgeOut,
    EdgesKind,
    EdgesKindCreate,
    EdgesKindOut,
    Kind,
    KindCreate,
    KindOut,
    Node,
    NodeCreate,
    NodeOut,
    NodeUpdate,
    SearchDatamodel,
    create_session_factory,
)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return None


def _database_url() -> str:
    """Return a SQLAlchemy database URL.

    Preferred input is DATABASE_URL.
    Fallback is split env vars commonly used in Kubernetes.
    """
    explicit = _first_env("DATABASE_URL")
    if explicit:
        return explicit

    host = _first_env("DATABASE_HOST")
    port_raw = _first_env("DATABASE_PORT") or "5432"
    user = _first_env("DATABASE_USER", "POSTGRES_USER")
    password = _first_env("DATABASE_PASSWORD", "DATABASE_PASS", "POSTGRES_PASSWORD")
    dbname = _first_env("DATABASE_NAME", "POSTGRES_DB")

    missing: List[str] = []
    if not host:
        missing.append("DATABASE_HOST")
    if not user:
        missing.append("DATABASE_USER")
    if not password:
        missing.append("DATABASE_PASSWORD")
    if not dbname:
        missing.append("DATABASE_NAME")

    try:
        port = int(port_raw)
    except ValueError:
        raise RuntimeError("DATABASE_PORT must be an integer") from None

    if missing:
        raise RuntimeError(
            "Missing required env vars: "
            + ", ".join(missing)
            + ". Set DATABASE_URL instead, or provide the split DATABASE_* variables."
        )

    assert host is not None
    assert user is not None
    assert password is not None
    assert dbname is not None

    # Project uses SQLAlchemy + psycopg3 (see requirements.txt)
    driver = os.getenv("DATABASE_DRIVER", "postgresql+psycopg")
    return (
        f"{driver}://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(dbname, safe='')}"
    )


def _attachments_dir() -> Path:
    return Path(os.getenv("ATTACHMENTS_DIR", "/tmp/attachments")).resolve()


def _validate_payload(
    schema: Dict[str, Any], payload: Dict[str, Any]
) -> List[Dict[str, Any]]:
    validator = jsonschema.Draft202012Validator(schema)
    errors: List[Dict[str, Any]] = []
    for err in sorted(validator.iter_errors(payload), key=str):
        errors.append(
            {
                "message": err.message,
                "path": list(err.path),
                "schema_path": list(err.schema_path),
            }
        )
    return errors


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine

    database_url = _database_url()
    # Create engine and store it for cleanup
    engine = create_engine(database_url, pool_pre_ping=True)
    app.state.engine = engine
    app.state.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )

    attachments_dir = _attachments_dir()
    attachments_dir.mkdir(parents=True, exist_ok=True)
    app.state.attachments_dir = attachments_dir
    yield
    # Cleanup on shutdown - dispose of database engine
    if hasattr(app.state, "engine"):
        app.state.engine.dispose()


app = FastAPI(title="Rhyolite API", lifespan=lifespan)

# Configure CORS. Set environment variable `CORS_ALLOW_ORIGINS` as a
# comma-separated list to override the default (useful in dev).
_cors_env = os.getenv("CORS_ALLOW_ORIGINS")
if _cors_env:
    _allow_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    # Default to the common local frontend origin used in this project
    _allow_origins = ["http://localhost:10000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db(request: Request):
    SessionLocal = request.app.state.SessionLocal
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _db_schema_ready(db: Session) -> bool:
    try:
        # Fast, cheap check: ensure at least the core table exists.
        return bool(
            db.execute(text("SELECT to_regclass('public.kinds') IS NOT NULL")).scalar()
        )
    except Exception:
        return False


@app.get("/healty")
def healty(db: Session = Depends(get_db)):
    if not _db_schema_ready(db):
        raise HTTPException(status_code=503, detail="Database schema not ready")

    return {
        "ok": True,
        "db_schema_ready": True,
        "allowed_origins": _allow_origins,
        "time": datetime.datetime.utcnow().isoformat(),
    }


def _get_node_or_404(db: Session, node_id: UUID) -> Node:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


def _get_kind_or_404(db: Session, name: str) -> Kind:
    kind = db.get(Kind, name)
    if kind is None:
        raise HTTPException(status_code=404, detail="Kind not found")
    return kind


def _delete_file_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        # Best-effort cleanup; DB integrity is still maintained.
        pass


@app.post("/kind", response_model=KindOut)
def create_kind(body: KindCreate, db: Session = Depends(get_db)):
    kind = Kind(name=body.name, schema=body.schema_)
    db.add(kind)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Kind already exists")
    db.refresh(kind)
    return kind


@app.get("/kind/{name}", response_model=KindOut)
def get_kind(name: str, db: Session = Depends(get_db)):
    return _get_kind_or_404(db, name)


@app.get("/kinds", response_model=List[KindOut])
def list_kinds(db: Session = Depends(get_db)):
    return list(db.scalars(select(Kind).order_by(Kind.name)).all())


@app.delete("/kind/{name}")
def delete_kind(name: str, db: Session = Depends(get_db)):
    kind = db.get(Kind, name)
    if kind is None:
        raise HTTPException(status_code=404, detail="Kind not found")

    node_count = db.scalar(
        select(func.count()).select_from(Node).where(Node.kind == name)
    )
    if node_count and node_count > 0:
        raise HTTPException(
            status_code=400, detail="Cannot delete kind with existing nodes"
        )

    db.delete(kind)
    db.commit()
    return {"ok": True}


@app.post("/edges-kind", response_model=EdgesKindOut)
def create_edges_kind(body: EdgesKindCreate, db: Session = Depends(get_db)):
    # Ensure kinds exist for clearer errors
    _get_kind_or_404(db, body.from_kind)
    _get_kind_or_404(db, body.to_kind)

    ek = EdgesKind(
        from_kind=body.from_kind, to_kind=body.to_kind, relation=body.relation
    )
    db.add(ek)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Edges kind already exists")
    return ek


@app.get("/edges-kinds", response_model=List[EdgesKindOut])
def list_edges_kinds(db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(EdgesKind).order_by(
                EdgesKind.from_kind, EdgesKind.to_kind, EdgesKind.relation
            )
        ).all()
    )


@app.get("/edges-kinds/{from_kind}", response_model=List[EdgesKindOut])
def list_edges_kinds_from(from_kind: str, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(EdgesKind)
            .where(EdgesKind.from_kind == from_kind)
            .order_by(EdgesKind.to_kind, EdgesKind.relation)
        ).all()
    )


@app.get("/edges-kinds/{from_kind}/{to_kind}", response_model=List[EdgesKindOut])
def list_edges_kinds_from_to(
    from_kind: str, to_kind: str, db: Session = Depends(get_db)
):
    return list(
        db.scalars(
            select(EdgesKind)
            .where(and_(EdgesKind.from_kind == from_kind, EdgesKind.to_kind == to_kind))
            .order_by(EdgesKind.relation)
        ).all()
    )


@app.get("/edges-kinds/{from_kind}/{to_kind}/{relation}", response_model=EdgesKindOut)
def get_edges_kind(
    from_kind: str, to_kind: str, relation: str, db: Session = Depends(get_db)
):
    ek = db.get(
        EdgesKind, {"from_kind": from_kind, "to_kind": to_kind, "relation": relation}
    )
    if ek is None:
        raise HTTPException(status_code=404, detail="Edges kind not found")
    return ek


@app.delete("/edges-kind/{from_kind}/{to_kind}/{relation}")
def delete_edges_kind(
    from_kind: str, to_kind: str, relation: str, db: Session = Depends(get_db)
):
    ek = db.get(
        EdgesKind, {"from_kind": from_kind, "to_kind": to_kind, "relation": relation}
    )
    if ek is None:
        raise HTTPException(status_code=404, detail="Edges kind not found")

    from_node = Node.__table__.alias("from_node")
    to_node = Node.__table__.alias("to_node")

    q = (
        select(func.count())
        .select_from(Edge.__table__)
        .join(from_node, from_node.c.id == Edge.__table__.c.from_id)
        .join(to_node, to_node.c.id == Edge.__table__.c.to_id)
        .where(
            and_(
                Edge.relation == relation,
                from_node.c.kind == from_kind,
                to_node.c.kind == to_kind,
            )
        )
    )
    edge_count = db.scalar(q)
    if edge_count and edge_count > 0:
        raise HTTPException(
            status_code=400, detail="Cannot delete edges kind used by existing edges"
        )

    db.delete(ek)
    db.commit()
    return {"ok": True}


@app.post("/node", response_model=NodeOut)
def create_node(body: NodeCreate, db: Session = Depends(get_db)):
    kind = db.get(Kind, body.kind)
    if kind is None:
        raise HTTPException(status_code=400, detail="Unknown kind")

    errors = _validate_payload(kind.schema, body.payload)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Payload does not match schema", "errors": errors},
        )

    node = Node(kind=body.kind, payload=body.payload)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@app.get("/node/{id}", response_model=NodeOut)
def get_node(id: UUID, db: Session = Depends(get_db)):
    return _get_node_or_404(db, id)


@app.put("/node/{id}", response_model=NodeOut)
def update_node(id: UUID, body: NodeUpdate, db: Session = Depends(get_db)):
    node = _get_node_or_404(db, id)
    kind = _get_kind_or_404(db, node.kind)

    errors = _validate_payload(kind.schema, body.payload)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Payload does not match schema", "errors": errors},
        )

    node.payload = body.payload
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@app.post("/nodes/search", response_model=List[NodeOut])
def search_nodes(body: SearchDatamodel, db: Session = Depends(get_db)):
    """Search nodes by dot-notated payload fields.

    Example queries:
    - {"name": "*alpha*"} -> payload.name ILIKE %alpha%
    - {"metadata.one": 2} -> payload.metadata.one == 2

    If `kinds` is omitted or null, all kinds are searched.
    """
    clauses = []

    # kinds filter
    if body.kinds:
        if len(body.kinds) > 0:
            clauses.append(Node.kind.in_(body.kinds))

    # Build clauses for each query item
    for key, val in body.query.items():
        path = key.split(".")
        # Use Postgres function jsonb_extract_path_text to get text at path
        expr = func.jsonb_extract_path_text(Node.payload, *path)

        if isinstance(val, str):
            if "*" in val:
                pattern = val.replace("*", "%")
                clauses.append(expr.ilike(pattern))
            else:
                clauses.append(expr == val)
        elif isinstance(val, bool):
            clauses.append(cast(expr, Boolean) == val)
        elif isinstance(val, (int, float)):
            clauses.append(cast(expr, Numeric) == val)
        elif val is None:
            clauses.append(expr.is_(None))
        else:
            # For arrays, objects, and other complex types, compare JSON text representation
            clauses.append(expr == json.dumps(val))

    q = select(Node)
    if clauses:
        q = q.where(and_(*clauses))

    if body.limit is not None:
        q = q.limit(body.limit)

    return list(db.scalars(q).all())


@app.delete("/node/{id}")
def delete_node(id: UUID, request: Request, db: Session = Depends(get_db)):
    node = db.get(Node, id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    # Delete attachment files before DB cascade removes rows.
    attachments_dir: Path = request.app.state.attachments_dir
    attachments = list(
        db.scalars(select(Attachment).where(Attachment.node_id == id)).all()
    )
    for att in attachments:
        _delete_file_quietly(attachments_dir / att.file_path)

    db.delete(node)
    db.commit()
    return {"ok": True}


@app.post("/edge", response_model=EdgeOut)
def create_edge(body: EdgeCreate, db: Session = Depends(get_db)):
    from_node = db.get(Node, body.from_id)
    if from_node is None:
        raise HTTPException(status_code=400, detail="from_id node not found")
    to_node = db.get(Node, body.to_id)
    if to_node is None:
        raise HTTPException(status_code=400, detail="to_id node not found")

    allowed = db.get(
        EdgesKind,
        {
            "from_kind": from_node.kind,
            "to_kind": to_node.kind,
            "relation": body.relation,
        },
    )
    if allowed is None:
        raise HTTPException(
            status_code=400, detail="Edge relationship not allowed by edges-kinds"
        )

    edge = Edge(from_id=body.from_id, to_id=body.to_id, relation=body.relation)
    db.add(edge)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Edge already exists")
    db.refresh(edge)
    return edge


@app.get("/outgoing-edges/{node_id}", response_model=List[EdgeOut])
def outgoing_edges(node_id: UUID, db: Session = Depends(get_db)):
    _get_node_or_404(db, node_id)
    return list(db.scalars(select(Edge).where(Edge.from_id == node_id)).all())


@app.get("/incoming-edges/{node_id}", response_model=List[EdgeOut])
def incoming_edges(node_id: UUID, db: Session = Depends(get_db)):
    _get_node_or_404(db, node_id)
    return list(db.scalars(select(Edge).where(Edge.to_id == node_id)).all())


@app.get("/edges/{from_id}/{to_id}", response_model=List[EdgeOut])
def edges_between(from_id: UUID, to_id: UUID, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Edge).where(and_(Edge.from_id == from_id, Edge.to_id == to_id))
        ).all()
    )


@app.delete("/edge/{from_id}/{to_id}/{relation}")
def delete_edge(
    from_id: UUID, to_id: UUID, relation: str, db: Session = Depends(get_db)
):
    edge = db.get(Edge, {"from_id": from_id, "to_id": to_id, "relation": relation})
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    db.delete(edge)
    db.commit()
    return {"ok": True}


@app.post("/attachment", response_model=AttachmentOut)
def create_attachment(
    request: Request,
    node_id: UUID = Form(...),
    file: UploadFile = File(...),
    name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _get_node_or_404(db, node_id)

    attachment_id = uuid4()
    mime_type = file.content_type or "application/octet-stream"

    # Determine attachment name: prefer URL query param 'name' if provided,
    # otherwise use the uploaded filename.
    attachment_name = (
        name
        if (name is not None and name != "")
        else (Path(file.filename).name if file.filename else "")
    )

    rel_path = Path(str(node_id)) / str(attachment_id)
    full_dir: Path = request.app.state.attachments_dir / str(node_id)
    full_dir.mkdir(parents=True, exist_ok=True)
    full_path: Path = request.app.state.attachments_dir / rel_path

    try:
        with full_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    att = Attachment(
        id=attachment_id,
        node_id=node_id,
        mime_type=mime_type,
        name=attachment_name,
        file_path=rel_path.as_posix(),
    )
    db.add(att)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _delete_file_quietly(full_path)
        raise HTTPException(status_code=409, detail="Attachment already exists")
    db.refresh(att)
    return att


@app.get("/attachment/{id}")
def get_attachment(id: UUID, request: Request, db: Session = Depends(get_db)):
    att = db.get(Attachment, id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    full_path: Path = request.app.state.attachments_dir / att.file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file missing")

    return FileResponse(
        path=str(full_path),
        media_type=att.mime_type,
        filename=str(att.id),
    )


@app.get("/attachments/{node_id}", response_model=List[AttachmentOut])
def list_attachments(node_id: UUID, db: Session = Depends(get_db)):
    _get_node_or_404(db, node_id)
    return list(
        db.scalars(select(Attachment).where(Attachment.node_id == node_id)).all()
    )


@app.delete("/attachment/{id}")
def delete_attachment(id: UUID, request: Request, db: Session = Depends(get_db)):
    att = db.get(Attachment, id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    full_path: Path = request.app.state.attachments_dir / att.file_path
    _delete_file_quietly(full_path)
    db.delete(att)
    db.commit()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    import signal
    import sys

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    # Handle shutdown signals gracefully
    def signal_handler(signum, frame):
        print(f"Received signal {signum}, shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    uvicorn.run(
        app,
        host=host,
        port=port,
        # Configure graceful shutdown
        access_log=False,  # Reduce logging during shutdown
        # These settings help with faster shutdown
        loop="uvloop" if os.getenv("UVLOOP", "true").lower() == "true" else "asyncio",
        # Server configuration for better shutdown handling
        server_header=False,
        date_header=False,
        # Shutdown timeout
        timeout_keep_alive=5,
    )
