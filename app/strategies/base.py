"""Abstract base class for all locking strategies."""
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
import structlog
from app.models import Campaign, SlotLockResult
from app.core.session_manager import SessionManager

logger = structlog.get_logger()


class BaseStrategy(ABC):
    """Abstract base for slot locking strategies.

    Each strategy must implement:
    - list_campaigns(): Discover open campaigns
    - lock_slot(): Attempt to lock a specific campaign slot
    - health_check(): Verify strategy is operational
    """

    name: str = "base"

    def __init__(self, session_manager: SessionManager):
        self.session = session_manager
        self.logger = logger.bind(strategy=self.name)

    @abstractmethod
    async def list_campaigns(self) -> List[Campaign]:
        """Fetch all campaigns with available slots.

        Returns:
            List of Campaign objects that have open slots.
        """
        pass

    @abstractmethod
    async def lock_slot(self, campaign_id: str) -> SlotLockResult:
        """Attempt to lock a slot on a campaign.

        Args:
            campaign_id: The campaign to lock.

        Returns:
            SlotLockResult with success/failure details.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the strategy can connect and authenticate.

        Returns:
            True if healthy, False otherwise.
        """
        pass

    async def preflight(self) -> bool:
        """Run pre-flight checks before using this strategy.

        Override to add strategy-specific validation.
        """
        if not self.session.is_valid:
            self.logger.warning("preflight.session_invalid")
            return False
        return True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"