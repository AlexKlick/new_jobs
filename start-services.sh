#!/bin/bash
# Start all Phase 8 services for new_job_denjobs v1.1 Assistant
# Usage: ./start-services.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "=== Starting Phase 8 Services ==="

# Kill any existing processes to ensure clean start
echo "Cleaning up old processes..."
for pidfile in "$SCRIPT_DIR"/vllm.pid "$SCRIPT_DIR"/chat_backend.pid "$SCRIPT_DIR"/voice_pipeline.pid; do
    if [ -f "$pidfile" ]; then
        oldpid=$(cat "$pidfile" 2>/dev/null)
        if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
            echo "  Killing old process $oldpid from $pidfile"
            kill "$oldpid" 2>/dev/null || true
        fi
        rm -f "$pidfile"
    fi
done

# 1. Start vLLM Nanbeige
echo "[1/3] Starting vLLM Nanbeige (GPU 0)..."
./start-llm.sh > "$LOG_DIR/start-llm.log" 2>&1 &
VLLM_PID=$!
echo "vLLM PID: $VLLM_PID"
echo $VLLM_PID > "$SCRIPT_DIR/vllm.pid"

# Wait for vLLM to be ready
echo "Waiting for vLLM to be ready..."
vllm_ready=false
for i in {1..60}; do
    if curl -s --max-time 5 http://localhost:8000/health > /dev/null 2>&1; then
        echo "vLLM ready after ${i} checks"
        vllm_ready=true
        break
    fi
    sleep 2
done

if [ "$vllm_ready" = false ]; then
    echo "WARNING: vLLM may not be ready. Check logs/start-llm.log"
fi

# 2. Start chat backend (port 8080)
echo "[2/3] Starting chat backend (port 8080)..."
source "$SCRIPT_DIR/.venv/bin/activate"
python chat_backend.py > "$LOG_DIR/chat_backend.log" 2>&1 &
CHAT_PID=$!
echo "Chat backend PID: $CHAT_PID"
echo $CHAT_PID > "$SCRIPT_DIR/chat_backend.pid"

# Wait for chat backend to be ready
echo "Waiting for chat backend..."
chat_ready=false
for i in {1..30}; do
    if curl -s --max-time 3 http://localhost:8080/health > /dev/null 2>&1; then
        echo "Chat backend ready"
        chat_ready=true
        break
    fi
    sleep 1
done

# 3. Start voice pipeline (port 8081)
echo "[3/3] Starting voice pipeline (port 8081)..."
python voice_pipeline.py > "$LOG_DIR/voice_pipeline.log" 2>&1 &
VOICE_PID=$!
echo "Voice pipeline PID: $VOICE_PID"
echo $VOICE_PID > "$SCRIPT_DIR/voice_pipeline.pid"

# Wait for voice pipeline to be ready
echo "Waiting for voice pipeline..."
voice_ready=false
for i in {1..30}; do
    if curl -s --max-time 3 http://localhost:8081/health > /dev/null 2>&1; then
        echo "Voice pipeline ready"
        voice_ready=true
        break
    fi
    sleep 1
done

echo ""
echo "=== All Services Started ==="
echo "vLLM:          http://localhost:8000 (PID: $VLLM_PID)"
echo "Chat Backend:   http://localhost:8080 (PID: $CHAT_PID)"
echo "Voice Pipeline: http://localhost:8081 (PID: $VOICE_PID)"
echo ""
echo "Frontend:       http://localhost:5173"
echo "Assistant UI:   http://localhost:5173/assistant"
echo ""
echo "Logs: $LOG_DIR/"

# Show health status
echo ""
echo "=== Health Checks ==="
curl -s --max-time 3 http://localhost:8000/health 2>/dev/null && echo " <- vLLM" || echo "vLLM: FAIL"
curl -s --max-time 3 http://localhost:8080/health 2>/dev/null && echo " <- chat_backend" || echo "chat_backend: FAIL"
curl -s --max-time 3 http://localhost:8081/health 2>/dev/null && echo " <- voice_pipeline" || echo "voice_pipeline: FAIL"
