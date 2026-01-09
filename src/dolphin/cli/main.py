"""
Main entry point for Dolphin CLI

This module provides the main() function that serves as the CLI entry point.
"""

import asyncio
import logging

from dolphin.cli.args.parser import parseArgs
from dolphin.cli.runner.runner import runDolphin
from dolphin.cli.utils.helpers import setupFlagsFromArgs


def main() -> None:
    """Main CLI entry point
    
    This function:
    1. Parses command-line arguments
    2. Sets up logging
    3. Configures feature flags
    4. Runs the dolphin program
    """
    args = parseArgs()
    
    # Setup logging
    from dolphin.core.logging.logger import setup_default_logger, set_log_level
    
    setup_default_logger(args.logSuffix)
    
    if args.logLevel:
        logLevelMap = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        set_log_level(logLevelMap.get(args.logLevel, logging.INFO))
    
    # Setup feature flags
    setupFlagsFromArgs(args)
    
    # Run
    asyncio.run(runDolphin(args))


if __name__ == "__main__":
    main()

