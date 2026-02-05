"""
Artifact Management Module

This module handles the saving and management of execution artifacts,
including execution traces and snapshot analysis for Dolphin agents.

Functions:
- saveExecutionArtifacts: Main function to save all execution artifacts
- _saveExecutionTrace: Save execution trace to file
- _saveSnapshotAnalysis: Save snapshot analysis in debug mode
"""

import asyncio
import datetime
import json
import os
import random
import traceback

from dolphin.core import flags
from dolphin.core.logging.logger import console
from dolphin.cli.args.parser import Args


async def saveExecutionArtifacts(agent, args: Args) -> None:
    """Save execution trace and snapshots

    Args:
        agent: Agent instance
        args: Parsed CLI arguments
    """
    if not args.saveHistory:
        return

    # Save trajectory if not already saved via trajectoryPath
    if not args.trajectoryPath:
        agent.save_trajectory(agent_name=args.agent, force_save=True)

    try:
        currentTime = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        randomSuffix = f"{random.randint(10000, 99999)}"

        # Save execution trace
        await _saveExecutionTrace(agent, args, currentTime, randomSuffix)

        # Save snapshot analysis in debug mode
        if flags.is_enabled(flags.DEBUG_MODE):
            await _saveSnapshotAnalysis(agent, args, currentTime, randomSuffix)

    except Exception as e:
        console(f"Warning: Failed to save execution trace: {e}")
        if args.saveHistory:
            traceback.print_exc()


async def _saveExecutionTrace(agent, args: Args, currentTime: str, randomSuffix: str) -> None:
    """Save execution trace to file"""
    traceContent = agent.get_execution_trace()

    if args.tracePath:
        tracePath = args.tracePath
        traceDir = os.path.dirname(tracePath)
        if traceDir:
            os.makedirs(traceDir, exist_ok=True)
    else:
        traceDir = "data/execution_trace"
        os.makedirs(traceDir, exist_ok=True)
        traceFilename = f"execution_trace_{currentTime}_{randomSuffix}.txt"
        tracePath = os.path.join(traceDir, traceFilename)

    with open(tracePath, "w", encoding="utf-8") as f:
        f.write(traceContent)

    console(f"Execution trace saved to: {tracePath}", verbose=args.saveHistory)


async def _saveSnapshotAnalysis(agent, args: Args, currentTime: str, randomSuffix: str) -> None:
    """Save snapshot analysis in debug mode"""
    try:
        snapshotDir = "data/snapshot_analysis"
        os.makedirs(snapshotDir, exist_ok=True)

        # Save Markdown format
        snapshotAnalysis = agent.get_snapshot_analysis(
            title=f"Debug Snapshot Analysis - {args.agent}"
        )
        snapshotFilename = f"snapshot_analysis_{currentTime}_{randomSuffix}.md"
        snapshotPath = os.path.join(snapshotDir, snapshotFilename)

        with open(snapshotPath, "w", encoding="utf-8") as f:
            f.write(snapshotAnalysis)

        console(f"Snapshot analysis saved to: {snapshotPath}", verbose=args.saveHistory)

        # Save JSON format
        snapshotJson = agent.get_snapshot_analysis(format='json')
        snapshotJsonFilename = f"snapshot_analysis_{currentTime}_{randomSuffix}.json"
        snapshotJsonPath = os.path.join(snapshotDir, snapshotJsonFilename)

        with open(snapshotJsonPath, "w", encoding="utf-8") as f:
            json.dump(snapshotJson, f, ensure_ascii=False, indent=2)

        console(f"Snapshot analysis JSON saved to: {snapshotJsonPath}", verbose=args.saveHistory)

    except Exception as e:
        console(f"Warning: Failed to save snapshot analysis: {e}")
        if args.saveHistory:
            traceback.print_exc()
