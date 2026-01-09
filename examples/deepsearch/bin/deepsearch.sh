#!/bin/bash

uv run --extra cli --extra lib ./bin/dolphin run \
    --folder examples/deepsearch/ \
    --agent deepsearch \
    --config examples/deepsearch/config/global.yaml \
    --user_id deepsearch_user \
    --session_id deepsearch_session \
    --query "$1" \
    --no-explore_block_v2 \
    --_max_answer_len 4096 \
    --verbose \
    --interactive
