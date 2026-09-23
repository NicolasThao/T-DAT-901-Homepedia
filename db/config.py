"""Connexions aux bases Homepedia, à partir de db/.env (cf. db/.env.example)."""

from pathlib import Path

import psycopg
import pymongo

DB_DIR = Path(__file__).resolve().parent


def _env():
    path = DB_DIR / ".env"
    if not path.exists():
        raise SystemExit("db/.env introuvable : copier db/.env.example vers db/.env")
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(l.split("=", 1) for l in lines if l.strip() and not l.startswith("#"))


def postgres():
    env = _env()
    return psycopg.connect(
        host="127.0.0.1",
        port=env["POSTGRES_PORT"],
        dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
    )


def mongo():
    env = _env()
    client = pymongo.MongoClient(
        host="127.0.0.1",
        port=int(env["MONGO_PORT"]),
        username=env["MONGO_USER"],
        password=env["MONGO_PASSWORD"],
        serverSelectionTimeoutMS=5000,
    )
    return client[env["MONGO_DB"]]
