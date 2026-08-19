#!/bin/bash
cd "$(dirname "$0")"
echo "Starting Apparatus Inventory Tracker..."
echo "Open the URL shown below in your browser."
streamlit run app.py --server.headless true --server.port 8501
