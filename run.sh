#!/bin/bash
# Portfolio Optimizer Runner Script

cd "$(dirname "$0")" || exit 1

# Activate virtual environment and run the script
source venv/bin/activate && python3 portfolio_optimizer.py
