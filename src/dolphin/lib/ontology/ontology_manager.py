"""
Ontology Manager Module
"""

import threading
from typing import Optional

from dolphin.lib.ontology.ontology import Ontology
from dolphin.core.config import OntologyConfig

# Add import of Dolphin SDK log
from dolphin.core.logging.logger import get_logger

logger = get_logger("ontology")


class OntologyManager:
    """Manage Ontology instances and are responsible for regularly synchronizing data sources."""

    def __init__(self, ontologyConfig: OntologyConfig, syncIntervalSeconds: int = 60):
        """Initialize the OntologyManager.

        Args:
            ontologyConfig (OntologyConfig): The ontology configuration.
            syncIntervalSeconds (int): The synchronization interval for data sources in seconds, default is 1 hour.
        """
        self.ontology: Ontology = Ontology(ontologyConfig)
        self.syncIntervalSeconds: int = syncIntervalSeconds
        self._syncThread: Optional[threading.Thread] = None
        self._stopEvent: threading.Event = threading.Event()
        self._syncLock: threading.Lock = threading.Lock()
        logger.debug(f"OntologyManager initialized，sync interval: {syncIntervalSeconds} s")

        self.ontology.buildOntologyFromSources(runScan=True, concurrent=True)
        logger.debug("OntologyManager Ontology build completed")

    def _synchronizeDataSource(self) -> None:
        """Background synchronization task, periodically triggering ontology data source scanning and building."""
        logger.debug("Ontology sync thread started")
        while not self._stopEvent.is_set():
            try:
                logger.debug("Starting ontology synchronization...")
                with self._syncLock:
                    # The actual synchronization logic, calling Ontology's methods here
                    # Assume that Ontology has a buildOntologyFromSources method for synchronization
                    # The parameters here may need to be adjusted according to the actual situation.
                    self.ontology.buildOntologyFromSources(
                        runScan=True, concurrent=True
                    )
                logger.debug("Ontology synchronization completed")

            except Exception as e:
                logger.exception(f"Error during ontology synchronization: {e}")

            # Wait for the next synchronization period or stop event
            self._stopEvent.wait(self.syncIntervalSeconds)

        logger.debug("Ontology sync thread stopped")

    def start(self) -> None:
        """Start the background synchronization thread."""
        if self._syncThread is not None and self._syncThread.is_alive():
            logger.warning("Sync thread is already running")
            return

        self._stopEvent.clear()
        self._syncThread = threading.Thread(
            target=self._synchronizeDataSource, daemon=True
        )
        self._syncThread.start()
        logger.debug("Requested to start ontology sync thread")

    def stop(self) -> None:
        """Stop the background synchronization thread."""
        if self._syncThread is None or not self._syncThread.is_alive():
            logger.debug("Sync thread is not running")
            return

        logger.debug("Requesting to stop ontology sync thread...")
        self._stopEvent.set()
        # You can choose to wait for the thread to finish, or return immediately.
        # self._syncThread.join()
        # logger.debug("The synchronization thread has been confirmed to have stopped")

    def triggerSyncNow(self) -> None:
        """Manually trigger a synchronization for this data source immediately."""
        logger.debug("Starting manual ontology synchronization...")
        try:
            with self._syncLock:
                # Assume that Ontology has a buildOntologyFromSources method for synchronization
                # The parameters here may need to be adjusted according to the actual situation.
                self.ontology.buildOntologyFromSources(runScan=True, concurrent=True)
            logger.debug("手动Ontology synchronization completed")
        except Exception as e:
            logger.exception(f"手动Error during ontology synchronization: {e}")

    def getOntology(self) -> Ontology:
        return self.ontology

    def getConcepts(self, concepts: list) -> list:
        return self.ontology.getConcepts(concepts)

    def getDataSourcesFromConcepts(self, concepts: list) -> list:
        return self.ontology.getDataSourcesFromConcepts(concepts)

    def getDataSourceSchemasFromConcepts(self, concepts: list) -> list:
        return self.ontology.getDataSourceSchemasFromConcepts(concepts)
