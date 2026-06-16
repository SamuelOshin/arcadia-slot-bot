"""EMERGENCY STRATEGY: AI-powered browser agent.

Last resort when both API and Playwright fail.
Uses vision-language models to understand and interact with the UI.
Slowest (~10-30s) but most resilient to UI changes.

Requires: OPENAI_API_KEY, browser-use package
"""
import time
from typing import List, Literal
from datetime import datetime, timedelta
import structlog
from app.config import settings
from app.models import Campaign, SlotLockResult
from app.strategies.base import BaseStrategy

logger = structlog.get_logger()


class AIAgentStrategy(BaseStrategy):
    """AI Agent strategy using browser-use + LLM.

    This is the emergency fallback. It's slow but can handle
    complex UI states, CAPTCHAs (with guidance), and unexpected
    page layouts that break Playwright selectors.
    """

    name = "ai_agent"

    def __init__(self, session_manager):
        super().__init__(session_manager)
        self._agent = None
        self._browser = None

    async def _ensure_agent(self):
        """Lazy-init the AI agent."""
        if self._agent:
            return self._agent

        try:
            from browser_use import Agent, Browser, BrowserConfig
            from langchain_openai import ChatOpenAI

            self._browser = Browser(config=BrowserConfig(headless=True))

            llm = ChatOpenAI(
                model=settings.ai_agent_model,
                api_key=settings.openai_api_key,
            )

            self._agent = Agent(
                task="",  # Will be set per-operation
                llm=llm,
                browser=self._browser,
                max_steps=settings.ai_agent_max_steps,
            )

            return self._agent

        except ImportError:
            logger.error("ai_agent.browser_use_not_installed")
            raise
        except Exception as e:
            logger.error("ai_agent.init_failed", error=str(e))
            raise

    async def list_campaigns(self) -> List[Campaign]:
        """Use AI agent to find and list campaigns."""
        start_time = time.time()

        try:
            agent = await self._ensure_agent()

            agent.task = """
            Go to https://arcadia-roster.up.railway.app/clip/campaigns
            Log in if needed using the saved browser session.
            Look at all the campaign cards on the page.
            For each campaign that has available slots (not "Full", not "Submitted", not "Closed"):
            - Extract the campaign ID
            - Extract the campaign title  
            - Extract the payout amount
            - Extract how many slots are remaining
            Return this information as a structured list.
            """

            result = await agent.run()

            # Parse the agent's output into Campaign objects
            # This is heuristic — the agent returns natural language
            campaigns = self._parse_agent_output(result)

            elapsed = (time.time() - start_time) * 1000
            self.logger.info("ai_agent.list_complete", count=len(campaigns), elapsed_ms=elapsed)

            return campaigns

        except Exception as e:
            self.logger.error("ai_agent.list_failed", error=str(e))
            return []

    async def lock_slot(self, campaign_id: str) -> SlotLockResult:
        """Use AI agent to lock a specific campaign slot."""
        start_time = time.time()

        try:
            agent = await self._ensure_agent()

            agent.task = f"""
            Go to https://arcadia-roster.up.railway.app/clip/campaigns/{campaign_id}
            Log in if needed.
            Look for a button to lock a slot on this campaign.
            Click that button.
            If a confirmation dialog appears, confirm it.
            Wait for the page to show a success message or update.
            Report whether the slot was successfully locked.
            """

            result = await agent.run()

            # Determine success from agent output
            success = any(word in result.lower() for word in ["success", "locked", "confirmed"])

            elapsed = (time.time() - start_time) * 1000

            return SlotLockResult(
                success=success,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"AI Agent result: {result[:200]}",
                strategy_used=self.name,
                response_time_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            self.logger.error("ai_agent.lock_failed", error=str(e))
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"AI Agent error: {str(e)}",
                strategy_used=self.name,
                response_time_ms=elapsed,
            )

    async def health_check(self) -> bool:
        """Check if AI agent dependencies are available."""
        if not settings.openai_api_key:
            return False
        try:
            import browser_use
            import langchain_openai
            return True
        except ImportError:
            return False

    def _parse_agent_output(self, output: str) -> List[Campaign]:
        """Heuristic parser for AI agent natural language output."""
        campaigns = []
        # This is a simplified parser — in production you'd use
        # structured output (JSON mode) or better prompting
        lines = output.split("\n")
        for line in lines:
            if "campaign" in line.lower() and any(c.isdigit() for c in line):
                # Extract what we can
                campaigns.append(Campaign(
                    _id="unknown",
                    campaignCode="unknown",
                    title=line[:100],
                    description="",
                    startDate=datetime.utcnow(),
                    endDate=datetime.utcnow() + timedelta(days=7),
                    maxSlots=100,
                    slotsLocked=0,
                    slotsRemaining=1,
                    kind="ugc",
                    status="active",
                    postPrice=10.0,
                ))
        return campaigns

    async def close(self):
        if self._browser:
            await self._browser.close()