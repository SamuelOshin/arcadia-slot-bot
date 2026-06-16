"""Aggregate all API routes."""
from fastapi import APIRouter
from app.api import health, campaigns, slots, dashboard

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(campaigns.router)
api_router.include_router(slots.router)
api_router.include_router(dashboard.router)