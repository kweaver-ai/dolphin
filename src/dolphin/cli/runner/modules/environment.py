"""
Environment Initialization Module

This module contains functions for initializing the Dolphin execution environment,
including environment setup, configuration loading, and feature flag management.
"""

import logging

from dolphin.core import flags
from dolphin.core.logging.logger import console
from dolphin.sdk.runtime.env import Env
from dolphin.core.config.global_config import GlobalConfig

from dolphin.cli.args.parser import Args


def _print_flags_status():
    """Print current status of all feature flags."""
    all_flags = flags.get_all()
    for flag_name, flag_value in sorted(all_flags.items()):
        state = "Enabled" if flag_value else "Disabled"
        console(f"[Flag] {flag_name}: {state}")


def _should_print_flags_status(args: Args) -> bool:
    """Return whether feature flags should be printed to console."""
    if flags.is_enabled(flags.DEBUG_MODE):
        return True
    log_level = str(getattr(args, "logLevel", "") or "").upper()
    return log_level == "DEBUG"


async def initializeEnvironment(args: Args):
    """Initialize Dolphin environment

    Args:
        args: Parsed CLI arguments

    Returns:
        Tuple of (env, globalConfig)
    """
    globalConfigPath = args.config if args.config else "./config/global.yaml"
    globalConfig = GlobalConfig.from_yaml(globalConfigPath)

    # Print flags status after loading config (flags may be set by config file)
    if _should_print_flags_status(args):
        _print_flags_status()

    env = Env(
        globalConfig=globalConfig,
        agentFolderPath=args.folder,
        skillkitFolderPath=args.skillFolder,
        output_variables=[],
        verbose=args.saveHistory,
        is_cli=True,  # CLI mode: enable Rich/terminal beautification
        log_level=(
            logging.DEBUG if flags.is_enabled(flags.DEBUG_MODE) else logging.INFO
        ),
    )

    return env, globalConfig
