"""HITL (Human-in-the-loop) 路由."""

from fastapi import APIRouter

router = APIRouter(prefix="/hitl", tags=["hitl"])
